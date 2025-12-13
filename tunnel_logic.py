import logging
import json
import asyncio
import html
import re
import shlex
import os
from datetime import datetime

# --- Telegram Imports ---
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

# --- Local Modules ---
import keyboard
from database import Database
from settings import KEY_FILE
from core import ServerMonitor, extract_safe_json

# --- Security Setup ---
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

class TunnelLogic:
    def __init__(self):
        self.db = Database()
        # اطمینان از وجود کلید
        if not os.path.exists(KEY_FILE):
            with open(KEY_FILE, 'wb') as f: f.write(Fernet.generate_key())
        with open(KEY_FILE, 'rb') as f: self.key = f.read()
        self.cipher = Fernet(self.key)

    def decrypt(self, txt):
        try: return self.cipher.decrypt(txt.encode()).decode()
        except: return ""

    async def run_mass_update_process(self, context, uid, subs, singles, monitor, status_msg):
        """اجرای عملیات آپدیت همگانی (ساب + تکی)"""
        ip, port, user = monitor['ip'], monitor['port'], monitor['username']
        password = self.decrypt(monitor['password'])
        
        final_report_groups = []
        
        # --- PHASE 1: SUBSCRIPTIONS ---
        for sub in subs:
            sub_name = sub['name']
            sub_link = sub['link']
            sub_id = sub['id']
            safe_sub_name = html.escape(sub_name)
            sub_report_lines = []

            # پاکسازی قدیمی‌ها جهت جلوگیری از تکرار
            with self.db.get_connection() as (conn, cur):
                cur.execute("DELETE FROM tunnel_configs WHERE owner_id=%s AND name LIKE %s AND type='sub_item'", (uid, f"{sub_name} | %"))
                conn.commit()

            # استفاده از -u برای خروجی لحظه‌ای
            cmd = f"python3 -u /root/monitor_agent.py {shlex.quote(sub_link)} 5.0"
            client = None
            try:
                client = ServerMonitor.get_ssh_client(ip, port, user, password)
                # استفاده از get_pty=True گاهی باعث بهم ریختن خروجی جیسون می‌شود، پس False می‌گذاریم یا با دقت هندل می‌کنیم
                # اینجا False امن‌تر است برای پارس کردن JSON
                stdin, stdout, stderr = client.exec_command(cmd)
                
                # خواندن خط به خط خروجی
                for line in iter(stdout.readline, ""):
                    line = line.strip()
                    if not line: continue
                    
                    # استخراج JSON از خط
                    json_match = re.search(r'(\{.*\})', line)
                    if json_match:
                        try:
                            data = json.loads(json_match.group(1))
                            
                            # نوع ۱: اطلاعات کلی ساب (Meta)
                            if data.get('type') == 'meta':
                                if 'sub_info' in data:
                                    info_str = json.dumps(data['sub_info'])
                                    with self.db.get_connection() as (conn, cur):
                                        cur.execute("UPDATE tunnel_configs SET sub_info=%s WHERE id=%s", (info_str, sub_id))
                                        conn.commit()

                            # نوع ۲: نتیجه تست کانفیگ (Result)
                            elif data.get('type') == 'result':
                                c_status = data.get('status')
                                c_name = data.get('name', 'Unknown')
                                c_link = data.get('link')
                                full_name = f"{sub_name} | {c_name}"
                                q_score = data.get('score', 0) if c_status == 'OK' else 0
                                now_dt = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                
                                # ذخیره در دیتابیس
                                with self.db.get_connection() as (conn, cur):
                                    cur.execute(
                                        """INSERT INTO tunnel_configs (owner_id, type, link, name, added_at, quality_score, last_status, last_ping, last_jitter, last_speed_down, last_speed_up) 
                                           VALUES (%s, 'sub_item', %s, %s, %s, %s, %s, %s, %s, %s, %s) 
                                           ON CONFLICT(link) DO NOTHING""",
                                        (uid, c_link, full_name, now_dt, q_score, c_status, data.get('ping',0), data.get('jitter',0), data.get('down',0), data.get('up',0))
                                    )
                                    conn.commit()

                                # افزودن به گزارش اگر سالم بود
                                if c_status == 'OK':
                                    line_txt = (f"<b>{html.escape(c_name)}</b>\n├ 📶 Ping: <code>{data.get('ping',0)}</code>\n└ ⭐️ Score: <code>{q_score}/10</code>")
                                    sub_report_lines.append(line_txt)
                                
                        except Exception as e:
                            logger.error(f"JSON Parse Error in Sub Loop: {e}")

            except Exception as e:
                sub_report_lines.append(f"❌ خطا در اتصال: {e}")
            finally:
                # بستن امن کانکشن
                if client:
                    try: client.close()
                    except: pass
            
            if sub_report_lines:
                final_report_groups.append({"title": f"📂 <b>{safe_sub_name}</b>", "lines": sub_report_lines})

        # --- PHASE 2: SINGLES ---
        if singles:
            single_report_lines = []
            client_single = None
            try:
                client_single = ServerMonitor.get_ssh_client(ip, port, user, password)
                for s_cfg in singles:
                    safe_name = html.escape(s_cfg['name'])
                    safe_link_arg = shlex.quote(s_cfg['link'])
                    # برای جیسون‌ها کوتیشن‌ها باید اسکیپ شوند
                    if s_cfg['type'] == 'json' or s_cfg['link'].strip().startswith('{'):
                         safe_link_arg = f"'{s_cfg['link'].replace(chr(39), '')}'" # حذف کوتیشن تکی مزاحم

                    cmd = f"python3 /root/monitor_agent.py {safe_link_arg} 5.0"
                    
                    try:
                        _, stdout, _ = client_single.exec_command(cmd, timeout=30) # تایم‌اوت جداگانه برای هر کانفیگ
                        output = stdout.read().decode().strip()
                        data = extract_safe_json(output)
                        
                        c_status = 'Fail'
                        q_score = 0
                        if data and data.get('status') == 'OK':
                            c_status = 'OK'
                            q_score = data.get('score', 0)
                            
                            with self.db.get_connection() as (conn, cur):
                                cur.execute("UPDATE tunnel_configs SET last_status='OK', last_ping=%s, last_jitter=%s, last_speed_down=%s, last_speed_up=%s, quality_score=%s WHERE id=%s",
                                    (data.get('ping',0), data.get('jitter',0), data.get('down',0), data.get('up',0), q_score, s_cfg['id']))
                                conn.commit()
                            
                            bar_filled = int(q_score)
                            progress_bar = "🟩" * bar_filled + "⬜️" * (10 - bar_filled)
                            report_txt = (f"<b>{safe_name}</b>\n📶 {data.get('ping',0)}ms | {progress_bar}")
                            single_report_lines.append(report_txt)
                        else:
                            with self.db.get_connection() as (conn, cur):
                                cur.execute("UPDATE tunnel_configs SET last_status='Fail' WHERE id=%s", (s_cfg['id'],))
                                conn.commit()
                    except:
                        # اگر یکی خطا داد، بعدی را چک کن
                        continue

            except Exception as e:
                single_report_lines.append(f"❌ خطا: {e}")
            finally:
                if client_single:
                    try: client_single.close()
                    except: pass

            if single_report_lines:
                final_report_groups.append({"title": f"👤 <b>کانفیگ‌های تکی</b>", "lines": single_report_lines})

        # --- FINAL REPORT ---
        try: await status_msg.delete()
        except: pass

        if not final_report_groups:
            await context.bot.send_message(chat_id=uid, text="❌ هیچ کانفیگ سالمی یافت نشد.")
            return

        header = f"📊 <b>گزارش نهایی تست همگانی</b>\n📦 تعداد منابع: {len(final_report_groups)}\n➖➖➖➖➖➖➖➖➖➖\n"
        await context.bot.send_message(chat_id=uid, text=header, parse_mode='HTML')
        
        for group in final_report_groups:
            chunk = f"{group['title']}\n➖➖➖➖➖➖➖➖\n"
            for line in group['lines']:
                if len(chunk) + len(line) > 4000:
                    await context.bot.send_message(chat_id=uid, text=chunk, parse_mode='HTML')
                    chunk = ""
                chunk += line + "\n" # خط جداکننده حذف شد برای فشردگی
            if chunk: await context.bot.send_message(chat_id=uid, text=chunk, parse_mode='HTML')

        kb = [[InlineKeyboardButton("🔙 بازگشت به لیست", callback_data='tunnel_list_menu')]]
        await context.bot.send_message(chat_id=uid, text="✅ **پایان عملیات.**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    async def finalize_sub_adding(self, update: Update, context: ContextTypes.DEFAULT_TYPE, temp_sub_link):
        """نهایی‌سازی افزودن اشتراک (دریافت اطلاعات از ایجنت و ذخیره)"""
        sub_name = update.message.text.strip()
        uid = update.effective_user.id
        safe_sub_name = html.escape(sub_name)
        status_msg = await update.message.reply_text(f"⏳ <b>در حال دریافت کانفیگ‌ها...</b>", parse_mode='HTML')
        
        with self.db.get_connection() as (conn, cur):
            cur.execute("SELECT * FROM servers WHERE is_monitor_node=1 AND is_active=1")
            monitor = cur.fetchone()
        
        if not monitor:
            await status_msg.edit_text("❌ سرور مانیتورینگ فعال نیست.")
            return ConversationHandler.END
            
        ip, port, user = monitor['ip'], monitor['port'], monitor['username']
        password = self.decrypt(monitor['password'])
        
        # استفاده از -u برای جلوگیری از بافرینگ
        cmd = f"python3 -u /root/monitor_agent.py {shlex.quote(temp_sub_link)}"
        
        client = None
        configs_to_insert = []
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        total_configs = 0
        success_count = 0

        try:
            # 1. ثبت سورس اشتراک
            with self.db.get_connection() as (conn, cur):
                cur.execute("INSERT INTO tunnel_configs (owner_id, type, link, name, added_at, quality_score) VALUES (%s, 'sub_source', %s, %s, %s, 10) ON CONFLICT(link) DO NOTHING", (uid, temp_sub_link, sub_name, now))
                conn.commit()
                # دریافت آیدی ساب ساخته شده
                cur.execute("SELECT id FROM tunnel_configs WHERE link=%s AND type='sub_source'", (temp_sub_link,))
                sub_db_row = cur.fetchone()
                sub_id = sub_db_row['id'] if sub_db_row else 0

            # 2. اتصال و اجرا
            client = ServerMonitor.get_ssh_client(ip, port, user, password)
            stdin, stdout, stderr = client.exec_command(cmd) # get_pty=False برای جلوگیری از کاراکترهای اضافی
            
            for line in iter(stdout.readline, ""):
                line = line.strip()
                if not line: continue
                
                json_match = re.search(r'(\{.*\})', line)
                if json_match:
                    try:
                        data = json.loads(json_match.group(1))
                        
                        if data.get('type') == 'meta':
                            total_configs = data.get('total', 0)
                            if sub_id and 'sub_info' in data:
                                info_str = json.dumps(data['sub_info'])
                                with self.db.get_connection() as (conn, cur):
                                    cur.execute("UPDATE tunnel_configs SET sub_info=%s WHERE id=%s", (info_str, sub_id))
                                    conn.commit()

                        elif data.get('type') == 'result':
                            # ساخت نام ترکیبی
                            item_name = data.get('name', 'Unknown')
                            full_name = f"{sub_name} | {item_name}"
                            link = data.get('link')
                            status = data.get('status')
                            
                            # کیفیت
                            q_score = 10 if status == 'OK' else 0
                            
                            if status == 'OK': success_count += 1
                            
                            configs_to_insert.append((
                                uid, link, full_name, now, q_score, status, 
                                data.get('ping', 0), data.get('jitter', 0), 
                                data.get('down', 0), data.get('up', 0)
                            ))
                            
                    except: pass
        except Exception as e:
            await status_msg.edit_text(f"❌ خطا: {str(e)[:100]}")
            return ConversationHandler.END
        finally:
            if client:
                try: client.close()
                except: pass

        # 3. ذخیره یکجا (Batch Insert)
        if configs_to_insert:
            with self.db.get_connection() as (conn, cur):
                cur.executemany(
                    """INSERT INTO tunnel_configs 
                       (owner_id, type, link, name, added_at, quality_score, last_status, last_ping, last_jitter, last_speed_down, last_speed_up) 
                       VALUES (%s, 'sub_item', %s, %s, %s, %s, %s, %s, %s, %s, %s) 
                       ON CONFLICT(link) DO NOTHING""", 
                    configs_to_insert
                )
                conn.commit()

        await status_msg.edit_text(f"🏁 <b>عملیات پایان یافت.</b>\n📂 {safe_sub_name}\n📊 کل: {total_configs}\n✅ سالم: {success_count}", parse_mode='HTML')
        await asyncio.sleep(2)
        return ConversationHandler.END

tunnel_manager = TunnelLogic()