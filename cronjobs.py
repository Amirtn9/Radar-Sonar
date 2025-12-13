import logging
import asyncio
import time
import json
import shlex
import socket  # اضافه شده برای تست TCP
import datetime as dt
from datetime import datetime, timedelta
from alerts import AlertManager
# --- Telegram Imports ---
from telegram.ext import ContextTypes
from server_stats import StatsManager
# --- Local Modules ---
import keyboard
from database import Database
from settings import (
    SUPER_ADMIN_ID, DOWN_RETRY_LIMIT, AGENT_FILE_PATH,
    SUBSCRIPTION_PLANS, DB_NAME, KEY_FILE
)
from core import (
    ServerMonitor, get_jalali_str, extract_safe_json, 
    get_tehran_datetime
)
from cryptography.fernet import Fernet
import os
import subprocess
from settings import DB_CONFIG  # برای دسترسی به یوزر و پسورد دیتابیس
# --- Logger Setup ---
logger = logging.getLogger(__name__)

# --- Initialize DB & Security for CronJobs ---
db = Database()

class Security:
    def __init__(self):
        if not os.path.exists(KEY_FILE):
            with open(KEY_FILE, 'wb') as f:
                f.write(Fernet.generate_key())
        with open(KEY_FILE, 'rb') as f:
            self.key = f.read()
        self.cipher = Fernet(self.key)

    def encrypt(self, txt):
        return self.cipher.encrypt(txt.encode()).decode()

    def decrypt(self, txt):
        try:
            return self.cipher.decrypt(txt.encode()).decode()
        except Exception as e:
            return ""

sec = Security()

# ==============================================================================
# 🧠 STATE TRACKERS
# ==============================================================================
SERVER_FAILURE_COUNTS = {}
CPU_ALERT_TRACKER = {}
DAILY_REPORT_USAGE = {}
TUNNEL_FAIL_STREAKS = {}
IS_SYSTEM_INITIALIZED = False

# کش برای جلوگیری از ارسال تکراری در یک دقیقه خاص (Wall Clock)
LAST_SERVER_REPORT_MIN = {}
LAST_CONFIG_REPORT_MIN = {}

# ==============================================================================
# 🛠 HELPER FUNCTIONS
# ==============================================================================

async def silent_update_monitor_agent():
    """آپدیت فایل ایجنت در پس‌زمینه (برای استارت‌آپ)"""
    try:
        loop = asyncio.get_running_loop()
        agent_content = ""
        if os.path.exists(AGENT_FILE_PATH):
            with open(AGENT_FILE_PATH, "r", encoding="utf-8") as f:
                agent_content = f.read()
        
        with db.get_connection() as conn:
            monitor = conn.execute("SELECT * FROM servers WHERE is_monitor_node=1 AND is_active=1").fetchone()
            
        if not monitor: return False 

        ip, port, user = monitor['ip'], monitor['port'], monitor['username']
        password = sec.decrypt(monitor['password'])

        def upload_process():
            try:
                client = ServerMonitor.get_ssh_client(ip, port, user, password)
                sftp = client.open_sftp()
                with sftp.file("/root/monitor_agent.py", "w") as remote_file:
                    remote_file.write(agent_content)
                sftp.close()
                commands = (
                    "apt-get update -y > /dev/null 2>&1; "
                    "apt-get install -y python3 python3-requests curl unzip > /dev/null 2>&1; "
                    "chmod 777 /root/agent_debug.log; "
                    "chmod +x /root/monitor_agent.py"
                )
                client.exec_command(commands, timeout=60)
                client.close()
                return True
            except: return False

        await loop.run_in_executor(None, upload_process)
        return True
    except: return False

async def run_global_commands_background(context, chat_id, servers, action):
    success_count = 0
    fail_count = 0
    msg_header = ""
    cmd = ""

    if action == 'update':
        msg_header = "🔄 **گزارش آپدیت خودکار**"
        cmd = "sudo DEBIAN_FRONTEND=noninteractive apt-get update -y && sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y"
    elif action == 'ram':
        msg_header = "🧹 **گزارش پاکسازی RAM**"
        cmd = "sync; echo 3 > /proc/sys/vm/drop_caches"
    elif action == 'disk':
        msg_header = "🗑 **گزارش پاکسازی دیسک**"
        cmd = "sudo apt-get autoremove -y && sudo apt-get clean && sudo journalctl --vacuum-time=1d"
    
    for srv in servers:
        try:
            ok, output = await asyncio.get_running_loop().run_in_executor(
                None, ServerMonitor.run_remote_command,
                srv['ip'], srv['port'], srv['username'], sec.decrypt(srv['password']),
                cmd, 600
            )
            if ok: success_count += 1
            else: fail_count += 1
        except: fail_count += 1

    final_report = (
        f"{msg_header}\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"📊 کل سرورها: {len(servers)}\n"
        f"✅ موفق: {success_count} | ❌ ناموفق: {fail_count}"
    )
    try:
        await context.bot.send_message(chat_id=chat_id, text=final_report, parse_mode='Markdown')
    except: pass

async def run_background_ssh_task(context, chat_id, func, *args):
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, func, *args)
    except: pass

async def check_server_down_logic(context, uid, s, res):
    """بررسی منطق قطعی سرور (با آلارم منیجر)"""
    k = (uid, s['id'])
    fails = SERVER_FAILURE_COUNTS.get(k, 0)

    if res['status'] == 'Offline':
        # اگر واقعاً آفلاین بود (بعد از تست‌های دقیق)
        fails += 1
        SERVER_FAILURE_COUNTS[k] = fails
        
        # اگر تعداد خطاها به حد نصاب رسید (برای جلوگیری از اسپم روی نوسان لحظه‌ای)
        if fails == DOWN_RETRY_LIMIT:
            alrt = AlertManager.get_down_alert_msg(s['name'], res.get('error', 'Time out'))
            
            user_channels = db.get_user_channels(uid)
            sent = False
            for c in user_channels:
                if c['usage_type'] in ['down', 'all']:
                    try:
                        tid = c['topic_id']
                        await context.bot.send_message(c['chat_id'], alrt, parse_mode='Markdown', message_thread_id=tid)
                        sent = True
                    except: pass
            if not sent:
                try: await context.bot.send_message(uid, alrt, parse_mode='Markdown')
                except: pass
            db.update_status(s['id'], "Offline")
    else:
        # اگر آنلاین شد و قبلاً آفلاین بود
        if s['last_status'] == 'Offline':
            SERVER_FAILURE_COUNTS[k] = 0
            rec_msg = AlertManager.get_recovery_msg(s['name'])
            user_channels = db.get_user_channels(uid)
            sent = False
            for c in user_channels:
                if c['usage_type'] in ['down', 'all']:
                    try:
                        tid = c['topic_id']
                        await context.bot.send_message(c['chat_id'], rec_msg, parse_mode='Markdown', message_thread_id=tid)
                        sent = True
                    except: pass
            
            if not sent:
                try: await context.bot.send_message(uid, rec_msg, parse_mode='Markdown')
                except: pass
            db.update_status(s['id'], "Online")
        elif fails > 0:
            # اگر خطاهایی داشتیم ولی هنوز به حد نصاب نرسیده بود و الان اوکی شد، ریست کن
            SERVER_FAILURE_COUNTS[k] = 0

async def process_single_user(context, uid, servers, settings, loop):
    """پردازش مانیتورینگ هوشمند سرور (سبک -> سنگین) + گزارش‌دهی دقیق سر ساعت"""
    
    # 🧠 تابع داخلی برای چک هوشمند (Smart Check Logic)
    def smart_server_check(ip, port, username, password):
        # 1. تست سبک (TCP Connect) - بسیار سریع
        # این تست فقط چک می‌کند آیا پورت SSH باز است یا خیر
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3) # 3 ثانیه تایم‌اوت برای تست سبک
            result = sock.connect_ex((ip, port))
            sock.close()
            is_reachable = (result == 0)
        except:
            is_reachable = False

        if is_reachable:
            # اگر پورت باز بود، حالا برای گرفتن آمار (CPU/RAM) وصل شو
            # چون می‌دانیم سرور زنده است، SSH معمولاً سریع وصل می‌شود
            return StatsManager.check_full_stats(ip, port, username, password)
        else:
            # 2. تست سنگین (تلاش مجدد در صورت شکست تست سبک)
            # شاید پکت لاس لحظه‌ای بوده، پس یک بار تلاش جدی با SSH می‌کنیم
            # با تایم‌اوت بیشتر (15 ثانیه)
            try:
                # متد check_full_stats خودش لاجیک اتصال Paramiko را دارد
                # ما اینجا فقط فراخوانی می‌کنیم اما چون پورت بسته بوده احتمالاً خطا می‌دهد
                # ولی برای اطمینان ۱۰۰٪ اجرا می‌کنیم
                retry_res = StatsManager.check_full_stats(ip, port, username, password)
                if retry_res['status'] == 'Online':
                    return retry_res
            except: pass
            
            # اگر هر دو مرحله شکست خورد، قطعی تایید است
            return {'status': 'Offline', 'error': 'Connection Refused (Confirmed)', 'uptime_sec': 0, 'traffic_gb': 0}

    tasks = []
    for s in servers:
        if s['is_active']:
            tasks.append(loop.run_in_executor(None, smart_server_check, s['ip'], s['port'], s['username'], sec.decrypt(s['password'])))
        else:
            async def fake(): return {'status': 'Disabled'}
            tasks.append(fake())

    results = await asyncio.gather(*tasks)
    
    # 3. پردازش نتایج و ارسال هشدار
    batch_stats = []
    
    for i, res in enumerate(results):
        s_info = servers[i]
        r = res if isinstance(res, dict) else await res

        if r.get('status') == 'Online':
            batch_stats.append((s_info['id'], r.get('cpu', 0), r.get('ram', 0)))
            
            # بررسی هشدار منابع
            warnings = AlertManager.check_resource_thresholds(r, settings)
            if warnings:
                last_alert = CPU_ALERT_TRACKER.get((uid, s_info['id']), 0)
                if time.time() - last_alert > 3600:
                    full_warning = AlertManager.get_resource_warning_msg(s_info['name'], warnings)
                    
                    user_channels = await loop.run_in_executor(None, db.get_user_channels, uid)
                    for ch in user_channels:
                        if ch['usage_type'] in ['resource', 'all']:
                            try:
                                tid = ch['topic_id']
                                await context.bot.send_message(ch['chat_id'], full_warning, parse_mode='Markdown', message_thread_id=tid)
                            except: pass
                    CPU_ALERT_TRACKER[(uid, s_info['id'])] = time.time()

        # بررسی منطق قطعی (با نتایج تست هوشمند)
        if settings['down_alert'] and s_info['is_active']:
            await check_server_down_logic(context, uid, s_info, r)

    if batch_stats:
        await loop.run_in_executor(None, db.add_server_stats_batch, batch_stats)

    # 4. منطق ارسال گزارش دوره‌ای (Wall Clock - سر ساعت دقیق)
    report_int_sec = settings.get('report_interval')
    
    if report_int_sec and int(report_int_sec) > 0:
        interval_min = int(report_int_sec) // 60
        now = datetime.now()
        current_minute_of_day = now.hour * 60 + now.minute
        
        # اگر زمان فعلی دقیقاً مضربی از تنظیم کاربر بود
        if interval_min > 0 and current_minute_of_day % interval_min == 0:
            last_sent = LAST_SERVER_REPORT_MIN.get(uid, -1)
            
            if last_sent != current_minute_of_day:
                header = f"📊 **گزارش خودکار سرورها**\n📅 `{get_jalali_str()}`\n➖➖➖➖➖➖\n"
                report_lines = []
                for i, res in enumerate(results):
                    s_info = servers[i]
                    r = res if isinstance(res, dict) else {}
                    if r.get('status') == 'Online':
                        cpu = r.get('cpu', 0)
                        ram = r.get('ram', 0)
                        icon = "🟢" if cpu < 50 else "🟡" if cpu < 80 else "🔴"
                        report_lines.append(f"{icon} **{s_info['name']}** | CPU: `{cpu}%` | RAM: `{ram}%`")
                    else:
                        report_lines.append(f"❌ **{s_info['name']}** | 🔌 OFFLINE")

                final_msg = header + "\n".join(report_lines)
                
                user_channels = await loop.run_in_executor(None, db.get_user_channels, uid)
                target_channels = [ch for ch in user_channels if ch['usage_type'] in ['report', 'all']]
                
                for ch in target_channels:
                    try:
                        tid = ch['topic_id']
                        await context.bot.send_message(ch['chat_id'], final_msg, parse_mode='Markdown', message_thread_id=tid)
                    except: pass
                
                LAST_SERVER_REPORT_MIN[uid] = current_minute_of_day

async def monitor_tunnels_job(context: ContextTypes.DEFAULT_TYPE):
    """مانیتورینگ دقیق کانفیگ‌ها (هوشمند: تست سبک -> تست سنگین)"""
    # 1. دریافت اطلاعات
    with db.get_connection() as conn:
        monitor_node = conn.execute("SELECT * FROM servers WHERE is_monitor_node = 1 AND is_active = 1").fetchone()
        configs = conn.execute("SELECT * FROM tunnel_configs").fetchall()

    if not monitor_node or not configs: return

    ip, port, user = monitor_node['ip'], monitor_node['port'], monitor_node['username']
    password = sec.decrypt(monitor_node['password'])
    loop = asyncio.get_running_loop()
    
    semaphore = asyncio.Semaphore(15) 

    async def check_single_config(cfg):
        async with semaphore:
            cid = cfg['id']
            name = cfg['name']
            old_status = cfg['last_status']
            link = cfg['link']
            
            # --- مرحله ۱: تست سبک (TCP Ping Mode) ---
            # سایز بسیار کم (0.1MB) و تایم‌اوت کوتاه (5 ثانیه)
            safe_link = shlex.quote(link)
            cmd_light = f"python3 /root/monitor_agent.py {safe_link} 0.1"
            
            ok, output = await loop.run_in_executor(None, ServerMonitor.run_remote_command, ip, port, user, password, cmd_light, 10)
            
            is_alive = False
            ping = 0
            
            if ok:
                res = extract_safe_json(output)
                if res and res.get("status") == "OK":
                    is_alive = True
                    ping = res.get('ping', 0)

            # --- مرحله ۲: تست سنگین (فقط در صورت شکست تست سبک) ---
            if not is_alive:
                # تست با حجم بیشتر (2.0MB) و تایم‌اوت طولانی (30 ثانیه)
                # این کار باعث می‌شود اگر اینترنت ضعیف بود، فرصت اتصال داشته باشد
                cmd_heavy = f"python3 /root/monitor_agent.py {safe_link} 2.0"
                ok_heavy, out_heavy = await loop.run_in_executor(None, ServerMonitor.run_remote_command, ip, port, user, password, cmd_heavy, 35)
                
                if ok_heavy:
                    res_h = extract_safe_json(out_heavy)
                    if res_h and res_h.get("status") == "OK":
                        is_alive = True
                        ping = res_h.get('ping', 0)

            # 3. آپدیت دیتابیس
            new_status = 'OK' if is_alive else 'Fail'
            now_time = datetime.now().strftime("%H:%M:%S")
            
            with db.get_connection() as conn:
                if is_alive:
                    conn.execute("UPDATE tunnel_configs SET last_status='OK', last_ping=?, quality_score=10 WHERE id=?", (ping, cid))
                else:
                    conn.execute("UPDATE tunnel_configs SET last_status='Fail', quality_score=0 WHERE id=?", (cid,))
                conn.commit()

            # 4. ارسال هشدار فوری (فقط در صورت تغییر وضعیت)
            alert_enabled = db.get_setting(cfg['owner_id'], 'config_alert_enabled') or '1'
            if alert_enabled == '0': return

            user_channels = db.get_user_channels(cfg['owner_id'])
            target_topics = [ch for ch in user_channels if ch['usage_type'] in ['config_alert', 'all']]
            
            if not target_topics: return

            msg = None
            if old_status == 'OK' and new_status == 'Fail':
                msg = f"❌ **هشدار قطعی کانفیگ**\n👤 `{name}`\n🕒 `{now_time}`\n⚠️ وضعیت: **قطع کامل (پس از بررسی دقیق)**"
            elif old_status == 'Fail' and new_status == 'OK':
                msg = f"✅ **بازگشت اتصال**\n👤 `{name}`\n🕒 `{now_time}`\n📶 پینگ: `{ping}ms`"

            if msg:
                for ch in target_topics:
                    try:
                        tid = ch['topic_id']
                        await context.bot.send_message(chat_id=ch['chat_id'], text=msg, parse_mode='Markdown', message_thread_id=tid)
                    except: pass

    # اجرای همزمان تست‌ها
    tasks = [check_single_config(c) for c in configs]
    if tasks:
        await asyncio.gather(*tasks)

    # --- بخش ارسال گزارش دوره‌ای (Wall Clock - سر ساعت دقیق) ---
    configs_by_user = {}
    for cfg in configs:
        uid = cfg['owner_id']
        if uid not in configs_by_user: configs_by_user[uid] = []
        configs_by_user[uid].append(cfg)

    now_obj = datetime.now()
    current_minute = now_obj.hour * 60 + now_obj.minute

    for uid, user_configs in configs_by_user.items():
        interval_min_str = db.get_setting(uid, 'config_report_interval') or '60'
        interval_min = int(interval_min_str)
        
        if interval_min == 0: continue
        
        if current_minute % interval_min == 0:
            last_sent = LAST_CONFIG_REPORT_MIN.get(uid, -1)
            
            if last_sent != current_minute:
                channels = db.get_user_channels(uid)
                target_channels = [c for c in channels if c['usage_type'] in ['config_report', 'all']]
                
                if not target_channels: continue

                total_c = len(user_configs)
                active_c = 0
                
                with db.get_connection() as conn:
                    for c in user_configs:
                        updated_c = conn.execute("SELECT last_status FROM tunnel_configs WHERE id=?", (c['id'],)).fetchone()
                        if updated_c and updated_c['last_status'] == 'OK':
                            active_c += 1
                
                failed_c = total_c - active_c
                stability = (active_c / total_c) * 100 if total_c > 0 else 0
                bar = StatsManager.make_bar(stability, 10)
                
                final_msg = (
                    f"📡 **گزارش خودکار کانفیگ‌ها**\n"
                    f"➖➖➖➖➖➖➖➖➖➖\n"
                    f"📊 **پایداری شبکه:** `{int(stability)}%`\n"
                    f"`{bar}`\n\n"
                    f"📦 کل: `{total_c}` | ✅ سالم: `{active_c}` | 🔴 قطع: `{failed_c}`\n\n"
                    f"💡 گزارش دقیق بر اساس تست‌های دو مرحله‌ای."
                )

                sent_any = False
                for ch in target_channels:
                    try:
                        tid = ch['topic_id']
                        await context.bot.send_message(chat_id=ch['chat_id'], text=final_msg, parse_mode='Markdown', message_thread_id=tid)
                        sent_any = True
                    except: pass
                
                if sent_any:
                    LAST_CONFIG_REPORT_MIN[uid] = current_minute

async def auto_update_subs_job(context: ContextTypes.DEFAULT_TYPE):
    """آپدیت خودکار ساب‌ها"""
    try:
        loop = asyncio.get_running_loop()
        def get_data():
            with db.get_connection() as conn:
                subs = conn.execute("SELECT * FROM tunnel_configs WHERE type='sub_source'").fetchall()
                monitor = conn.execute("SELECT * FROM servers WHERE is_monitor_node=1 AND is_active=1").fetchone()
            return subs, monitor
        subs, monitor = await loop.run_in_executor(None, get_data)
        if not subs or not monitor: return
        ip, port, user = monitor['ip'], monitor['port'], monitor['username']
        password = sec.decrypt(monitor['password'])
        for sub in subs:
            cmd = f"python3 -u /root/monitor_agent.py '{sub['link']}'"
            try:
                ok, output = await loop.run_in_executor(None, ServerMonitor.run_remote_command, ip, port, user, password, cmd, 45)
                if ok:
                    import re
                    match = re.search(r'(\{.*"type":\s*"meta".*\})', output)
                    if match:
                        data = json.loads(match.group(1))
                        if 'sub_info' in data:
                            info_str = json.dumps(data['sub_info'])
                            with db.get_connection() as conn:
                                conn.execute("UPDATE tunnel_configs SET sub_info=? WHERE id=?", (info_str, sub['id']))
                                conn.commit()
            except: continue
    except: pass

async def auto_backup_send_job(context: ContextTypes.DEFAULT_TYPE):
    """بکاپ‌گیری خودکار از دیتابیس Postgres"""
    if not SUPER_ADMIN_ID: return

    # نام فایل بکاپ
    timestamp = get_tehran_datetime().strftime("%Y-%m-%d_%H-%M")
    backup_file = f"backup_{timestamp}.sql"

    try:
        # تنظیم پسورد در متغیر محیطی برای pg_dump
        env = os.environ.copy()
        env['PGPASSWORD'] = DB_CONFIG['password']

        # دستور اجرای pg_dump
        cmd = [
            "pg_dump",
            "-h", DB_CONFIG['host'],
            "-U", DB_CONFIG['user'],
            "-d", DB_CONFIG['dbname'],
            "-f", backup_file
        ]

        # اجرای دستور در پس‌زمینه (بدون بلاک کردن ربات)
        proc = await asyncio.create_subprocess_exec(*cmd, env=env)
        await proc.wait()

        if proc.returncode == 0:
            with open(backup_file, 'rb') as f:
                await context.bot.send_document(
                    chat_id=SUPER_ADMIN_ID, 
                    document=f, 
                    filename=backup_file, 
                    caption=f"📦 Auto Backup (Postgres)\n📅 {get_jalali_str()}"
                )
        else:
            logger.error("Backup process failed with non-zero exit code.")

    except Exception as e:
        logger.error(f"Auto Backup Error: {e}")
    finally:
        # پاک کردن فایل موقت
        if os.path.exists(backup_file):
            os.remove(backup_file)

async def auto_scheduler_job(context: ContextTypes.DEFAULT_TYPE):
    """بررسی وظایف زمان‌بندی شده کاربر (آپدیت/ریبوت خودکار)"""
    loop = asyncio.get_running_loop()
    users = await loop.run_in_executor(None, db.get_all_users)
    now = time.time()
    tehran_now = get_tehran_datetime()
    current_hhmm = tehran_now.strftime("%H:%M")
    today_date_str = tehran_now.strftime("%Y-%m-%d")
    today_date_obj = datetime.strptime(today_date_str, "%Y-%m-%d").date()

    for user in users:
        uid = user['user_id']
        
        # 1. آپدیت خودکار
        up_interval = db.get_setting(uid, 'auto_update_hours')
        if up_interval and up_interval != '0':
            last_run = int(db.get_setting(uid, 'last_auto_update_run') or 0)
            interval_sec = int(up_interval) * 3600
            if now - last_run > interval_sec:
                servers = db.get_all_user_servers(uid)
                active = [s for s in servers if s['is_active']]
                if active:
                    try: await context.bot.send_message(uid, f"🔄 **شروع آپدیت خودکار...**")
                    except: pass
                    asyncio.create_task(run_global_commands_background(context, uid, active, 'update'))
                db.set_setting(uid, 'last_auto_update_run', int(now))

        # 2. ریبوت خودکار
        reb_config = db.get_setting(uid, 'auto_reboot_config')
        if reb_config and reb_config != 'OFF' and '|' in reb_config:
            try:
                interval_days_str, target_time = reb_config.split('|')
                interval_days = int(interval_days_str)
                if current_hhmm == target_time:
                    last_reb_str = db.get_setting(uid, 'last_reboot_date') or '2000-01-01'
                    last_reb_date = datetime.strptime(last_reb_str, "%Y-%m-%d").date()
                    days_diff = (today_date_obj - last_reb_date).days
                    if days_diff >= interval_days:
                        servers = db.get_all_user_servers(uid)
                        active = [s for s in servers if s['is_active']]
                        if active:
                            for s in active:
                                asyncio.create_task(run_background_ssh_task(context, uid, ServerMonitor.run_remote_command, s['ip'], s['port'], s['username'], sec.decrypt(s['password']), "reboot"))
                        db.set_setting(uid, 'last_reboot_date', today_date_str)
            except: pass

async def global_monitor_job(context: ContextTypes.DEFAULT_TYPE):
    """مانیتورینگ کلی سرورها (هر ۱ دقیقه اجرا می‌شود)"""
    loop = asyncio.get_running_loop()
    users_list = await loop.run_in_executor(None, db.get_all_users)
    all_users = set([u['user_id'] for u in users_list] + [SUPER_ADMIN_ID])
    semaphore = asyncio.Semaphore(10)

    async def protected_process(uid):
        async with semaphore:
            servers = await loop.run_in_executor(None, db.get_all_user_servers, uid)
            if not servers: return
            def get_user_settings():
                return {
                    'report_interval': db.get_setting(uid, 'report_interval'),
                    'cpu': int(db.get_setting(uid, 'cpu_threshold') or 80),
                    'ram': int(db.get_setting(uid, 'ram_threshold') or 80),
                    'disk': int(db.get_setting(uid, 'disk_threshold') or 90),
                    'down_alert': db.get_setting(uid, 'down_alert_enabled') == '1'
                }
            settings = await loop.run_in_executor(None, get_user_settings)
            await process_single_user(context, uid, servers, settings, loop)

    all_tasks = [protected_process(uid) for uid in all_users]
    if all_tasks: await asyncio.gather(*all_tasks)

async def check_bonus_expiry_job(context: ContextTypes.DEFAULT_TYPE):
    """بررسی و حذف پاداش‌های منقضی شده"""
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with db.get_connection() as conn:
        expired = conn.execute("SELECT * FROM temp_bonuses WHERE expires_at < ?", (now_str,)).fetchall()
        for bonus in expired:
            uid = bonus['user_id']
            amount = bonus['bonus_limit']
            user = conn.execute("SELECT server_limit FROM users WHERE user_id = ?", (uid,)).fetchone()
            if user:
                new_limit = max(0, user['server_limit'] - amount)
                conn.execute("UPDATE users SET server_limit = ? WHERE user_id = ?", (new_limit, uid))
                try:
                    await context.bot.send_message(uid, f"⚠️ **پایان پاداش دعوت**\nظرفیت سرور شما کاهش یافت.")
                except: pass
            conn.execute("DELETE FROM temp_bonuses WHERE id = ?", (bonus['id'],))
        conn.commit()

async def check_expiry_job(context: ContextTypes.DEFAULT_TYPE):
    """بررسی انقضای سرورها (روزانه)"""
    users = db.get_all_users()
    today = datetime.now().date()
    for user in users:
        uid = user['user_id']
        servers = db.get_all_user_servers(uid)
        user_channels = db.get_user_channels(uid)
        target_channels = [c for c in user_channels if c.get('usage_type', 'all') in ['expiry', 'all']]

        for srv in servers:
            if not srv['expiry_date']: continue
            try:
                exp_date = datetime.strptime(srv['expiry_date'], '%Y-%m-%d').date()
                days_left = (exp_date - today).days
                msg = None
                if days_left == 3:
                    msg = f"⚠️ **هشدار انقضا (۳ روز مانده)**\n🖥 `{srv['name']}`"
                elif days_left == 0:
                    msg = f"🚨 **هشدار نهایی (امروز تمام می‌شود)**\n🖥 `{srv['name']}`"

                if msg:
                    try: await context.bot.send_message(uid, msg, parse_mode='Markdown')
                    except: pass
                    for ch in target_channels:
                        try: await context.bot.send_message(ch['chat_id'], msg, parse_mode='Markdown')
                        except: pass
            except: pass

async def startup_whitelist_job(context: ContextTypes.DEFAULT_TYPE):
    loop = asyncio.get_running_loop()
    bot_ip = await loop.run_in_executor(None, ServerMonitor.get_bot_public_ip)
    if not bot_ip: return
    with db.get_connection() as conn:
        servers = conn.execute("SELECT * FROM servers").fetchall()
    for srv in servers:
        try:
            real_pass = sec.decrypt(srv['password'])
            await loop.run_in_executor(None, ServerMonitor.whitelist_bot_ip, srv['ip'], srv['port'], srv['username'], real_pass, bot_ip)
        except: pass

async def send_startup_topic_test(context: ContextTypes.DEFAULT_TYPE):
    if not SUPER_ADMIN_ID: return
    channels = db.get_user_channels(SUPER_ADMIN_ID)
    if not channels: return
    for ch in channels:
        if ch['topic_id']:
            try:
                await context.bot.send_message(chat_id=ch['chat_id'], text=f"✅ **سیستم آماده است.**\nتاپیک: {ch['usage_type']}", parse_mode='Markdown', message_thread_id=ch['topic_id'])
            except: pass

async def system_startup_notification(context: ContextTypes.DEFAULT_TYPE):
    global IS_SYSTEM_INITIALIZED
    asyncio.create_task(silent_update_monitor_agent())
    IS_SYSTEM_INITIALIZED = True
    if not SUPER_ADMIN_ID: return
    loop = asyncio.get_running_loop()
    is_monitor_ready = await loop.run_in_executor(None, db.is_monitor_active)
    reply_markup = keyboard.main_menu_kb(SUPER_ADMIN_ID, is_monitor_ready, SUPER_ADMIN_ID)
    try:
        await context.bot.send_message(chat_id=SUPER_ADMIN_ID, text="🚀 **ربات با موفقیت ریستارت شد.**\n✅ سیستم آماده است.", reply_markup=reply_markup, parse_mode='Markdown')
    except: pass