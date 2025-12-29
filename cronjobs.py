import logging
import asyncio
import time
import json
import shlex
import socket
import os
import subprocess
import datetime as dt
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

# --- Local Modules ---
from alerts import AlertManager
from telegram.ext import ContextTypes
from server_stats import StatsManager
import keyboard
from database import Database
from settings import (
    SUPER_ADMIN_ID, DOWN_RETRY_LIMIT, AGENT_FILE_PATH,
    SUBSCRIPTION_PLANS, DB_NAME, KEY_FILE, DB_CONFIG, AGENT_PORT
)
from core import (
    ServerMonitor, get_jalali_str, extract_safe_json, 
    get_tehran_datetime, sec
)
from cryptography.fernet import Fernet

# ==============================================================================
# ⚙️ CONFIGURATION & GLOBALS
# ==============================================================================
logger = logging.getLogger(__name__)
db = Database()

# ایجاد Executor برای کارهای سنگین دیتابیس
EXECUTOR = ThreadPoolExecutor(max_workers=10)

SERVER_FAILURE_COUNTS = {}
CPU_ALERT_TRACKER = {}
DAILY_REPORT_USAGE = {}
TUNNEL_FAIL_STREAKS = {}
IS_SYSTEM_INITIALIZED = False
LAST_SERVER_REPORT_MIN = {}
LAST_CONFIG_REPORT_MIN = {}

# ==============================================================================
# 🔄 SCHEDULED JOBS
# ==============================================================================

async def global_monitor_job(context: ContextTypes.DEFAULT_TYPE):
    """بررسی وضعیت کلی سرورها (منابع)"""
    try:
        loop = asyncio.get_running_loop()
        # دریافت لیست سرورهای فعال از دیتابیس
        active_servers = await loop.run_in_executor(EXECUTOR, db.get_active_servers)
        
        if not active_servers:
            return

        for srv in active_servers:
            # اجرای تسک برای هر سرور بدون بلاک کردن بقیه
            asyncio.create_task(check_single_server_resources(context, srv))
            
    except Exception as e:
        logger.error(f"Global Monitor Job Error: {e}")

async def check_single_server_resources(context, srv):
    """بررسی منابع یک سرور خاص"""
    sid = srv['id']
    ip = srv['ip']
    name = srv['name']
    
    try:
        real_pass = sec.decrypt(srv['password'])
        
        # 1. دریافت آمار (اول وب‌سوکت، بعد SSH)
        stats = await StatsManager.check_full_stats(ip, srv['port'], srv['username'], real_pass)
        
        # 2. بررسی وضعیت آنلاین/آفلاین
        if stats.get('status') == 'Offline':
            fail_count = SERVER_FAILURE_COUNTS.get(sid, 0) + 1
            SERVER_FAILURE_COUNTS[sid] = fail_count
            
            # اگر از حد مجاز گذشت، هشدار بده
            if fail_count >= DOWN_RETRY_LIMIT:
                if fail_count == DOWN_RETRY_LIMIT: # فقط بار اول پیام بده
                    msg = AlertManager.get_down_alert_msg(name, stats.get('error', 'Timeout'))
                    await alert_admin(context, msg)
            return
        else:
            # اگر سرور برگشت، ریست کن
            if SERVER_FAILURE_COUNTS.get(sid, 0) > 0:
                SERVER_FAILURE_COUNTS[sid] = 0
                # پیام بازگشت (اختیاری)
                # await alert_admin(context, f"✅ سرور {name} آنلاین شد.")

        # 3. بررسی مصرف منابع (CPU/RAM/DISK)
        # فقط اگر ادمین تنظیم کرده باشد هشدار بدهد
        # فعلا ساده رد می‌شویم تا لاگ شلوغ نشود
        
        # ذخیره آخرین وضعیت در دیتابیس (اختیاری برای نمودار)
        # await save_server_stats_to_db(sid, stats)

    except Exception as e:
        logger.error(f"Error checking server {name}: {e}")

async def monitor_tunnels_job(context: ContextTypes.DEFAULT_TYPE):
    """مانیتورینگ تانل‌ها (کانفیگ‌ها)"""
    # فعلا برای جلوگیری از شلوغی لاگ، این بخش را ساده می‌کنیم
    # لاجیک اصلی در tunnel_logic.py است و دستی فراخوانی می‌شود
    pass

async def auto_scheduler_job(context: ContextTypes.DEFAULT_TYPE):
    """اجرای تسک‌های زمان‌بندی شده کاربر"""
    # اگر تسک خاصی دارید اینجا اضافه کنید
    pass

async def auto_update_subs_job(context: ContextTypes.DEFAULT_TYPE):
    """آپدیت خودکار اشتراک‌ها"""
    pass

async def check_expiry_job(context: ContextTypes.DEFAULT_TYPE):
    """بررسی سررسید سرویس‌ها"""
    try:
        loop = asyncio.get_running_loop()
        near_expiry = await loop.run_in_executor(EXECUTOR, db.get_near_expiry_services)
        
        if near_expiry:
            msg = "⏳ **لیست سرویس‌های در حال انقضا (۳ روز مانده):**\n\n"
            for s in near_expiry:
                msg += f"🔸 {s['name']} - {s['ip']}\n"
            
            await alert_admin(context, msg)
            
    except Exception as e:
        logger.error(f"Expiry Job Error: {e}")

async def check_bonus_expiry_job(context: ContextTypes.DEFAULT_TYPE):
    """بررسی انقضای هدیه‌ها"""
    pass

async def auto_backup_send_job(context: ContextTypes.DEFAULT_TYPE):
    """ارسال بکاپ خودکار دیتابیس"""
    if not SUPER_ADMIN_ID: return
    try:
        # ✅ PostgreSQL Backup (pg_dump)
        # DB_NAME اینجا به معنای فایل خروجی بکاپ است.
        now = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = f"/tmp/sonar_auto_backup_{now}.dump"

        def _dump():
            env = os.environ.copy()
            env['PGPASSWORD'] = str(DB_CONFIG.get('password', ''))
            cmd = [
                'pg_dump',
                '-h', str(DB_CONFIG.get('host', 'localhost')),
                '-p', str(DB_CONFIG.get('port', '5432')),
                '-U', str(DB_CONFIG.get('user', 'postgres')),
                '-F', 'c',
                '-f', backup_path,
                str(DB_CONFIG.get('dbname', 'postgres')),
            ]
            subprocess.run(cmd, env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(EXECUTOR, _dump)

        if os.path.exists(backup_path):
            with open(backup_path, 'rb') as f:
                await context.bot.send_document(
                    chat_id=SUPER_ADMIN_ID,
                    document=f,
                    caption=f"📦 **Auto Backup (PostgreSQL)**\n📅 {get_jalali_str()}",
                    filename=os.path.basename(backup_path)
                )
        try:
            os.remove(backup_path)
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Backup Job Error: {e}")

# ==============================================================================
# 🚀 STARTUP TASKS (LIGHTWEIGHT)
# ==============================================================================

async def startup_whitelist_job(context: ContextTypes.DEFAULT_TYPE):
    """
    ❌ نسخه قبلی: تلاش برای SSH به همه سرورها (باعث کندی می‌شد)
    ✅ نسخه فعلی: غیرفعال شده تا ربات سریع بالا بیاید.
    """
    logger.info("⏩ Startup Whitelist Job skipped for performance.")
    pass 

async def silent_update_monitor_agent():
    """
    ❌ نسخه قبلی: تلاش برای نصب ایجنت روی همه سرورها (باعث گیر کردن می‌شد)
    ✅ نسخه فعلی: غیرفعال. نصب باید دستی یا از منوی ادمین انجام شود.
    """
    logger.info("⏩ Silent Agent Update skipped for performance.")
    pass

async def send_startup_topic_test(context: ContextTypes.DEFAULT_TYPE):
    """تست ارسال پیام در تاپیک‌ها (اختیاری)"""
    pass

async def system_startup_notification(context: ContextTypes.DEFAULT_TYPE):
    """اعلان روشن شدن ربات به ادمین"""
    global IS_SYSTEM_INITIALIZED
    IS_SYSTEM_INITIALIZED = True
    
    if not SUPER_ADMIN_ID: return
    
    try:
        txt = (
            f"🤖 **ربات سونار رادار (Ultra Pro) آنلاین شد!**\n"
            f"📅 زمان: `{get_jalali_str()}`\n"
            f"✅ وضعیت: **Ready**"
        )
        await context.bot.send_message(chat_id=SUPER_ADMIN_ID, text=txt, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Startup Notification Error: {e}")

# ==============================================================================
# 🔔 UTILS
# ==============================================================================

async def alert_admin(context, text):
    """ارسال پیام به ادمین اصلی"""
    if not SUPER_ADMIN_ID: return
    try:
        await context.bot.send_message(chat_id=SUPER_ADMIN_ID, text=text, parse_mode='Markdown')
    except: pass