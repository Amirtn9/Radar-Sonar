import logging
import traceback
import os
import json
import asyncio
import time
import warnings
import threading
import statistics
import io
import html
import re
import base64
import urllib.parse
import shlex
import datetime as dt
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import topics
import subprocess
from settings import DB_CONFIG  # برای دسترسی به یوزر و پسورد دیتابیس
# --- Third-Party Libraries ---
import jdatetime
from cryptography.fernet import Fernet
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.error import BadRequest, TelegramError, Conflict, NetworkError
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ConversationHandler, JobQueue
)

# --- Local Modules ---
from logger_setup import setup_logger
import keyboard
import admin_panel
import cronjobs
from database import Database
from tunnel_logic import tunnel_manager
from server_stats import StatsManager
from scoring import ScoreEngine
from core import (
    ServerMonitor, get_jalali_str, generate_plot, 
    get_tehran_datetime, extract_safe_json
)
from settings import (
    DB_NAME, CONFIG_FILE, KEY_FILE, AGENT_FILE_PATH, 
    SUBSCRIPTION_PLANS, PAYMENT_INFO, DEFAULT_INTERVAL, 
    DOWN_RETRY_LIMIT, SUPER_ADMIN_ID
)

# ==============================================================================
# 🚀 INITIALIZATION & CONFIGURATION
# ==============================================================================

logger = setup_logger()
warnings.filterwarnings("ignore")

def get_agent_content():
    """خواندن محتوای فایل ایجنت به صورت داینامیک"""
    try:
        if os.path.exists(AGENT_FILE_PATH):
            with open(AGENT_FILE_PATH, "r", encoding="utf-8") as f:
                return f.read()
        return ""
    except Exception as e:
        logger.error(f"❌ Error loading agent script: {e}")
        return ""

print(f"✅ Agent Script Status: {'Found' if get_agent_content() else 'Not Found (Will retry later)'}")

# ==============================================================================
# ⚙️ DYNAMIC CONFIGURATION
# ==============================================================================
try:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
            TOKEN = config.get('bot_token', 'Not_Set')
            try:
                SUPER_ADMIN_ID = int(config.get('admin_id', SUPER_ADMIN_ID))
            except:
                pass 
    else:
        TOKEN = 'TOKEN_NOT_SET'
        print(f"⚠️ Config file ({CONFIG_FILE}) not found. Please run install.sh")
except Exception as e:
    logger.error(f"❌ Error loading config: {e}")
    TOKEN = 'ERROR'

# --- Global Cache & State Trackers ---
UPTIME_MILESTONE_TRACKER = set()
SSH_SESSION_CACHE = {}
USER_ACTIVE_TASKS = {}

# --- Conversation States ---
(
    GET_NAME, GET_IP, GET_PORT, GET_USER, GET_PASS, SELECT_GROUP,          
    GET_GROUP_NAME, GET_CHANNEL_FORWARD, GET_MANUAL_HOST,                  
    ADD_ADMIN_ID, ADD_ADMIN_DAYS, ADMIN_SEARCH_USER,                       
    ADMIN_SET_LIMIT, ADMIN_RESTORE_DB, ADMIN_RESTORE_KEY, ADMIN_SET_TIME_MANUAL, 
    GET_CUSTOM_INTERVAL, GET_EXPIRY, GET_CHANNEL_TYPE,                     
    EDIT_SERVER_EXPIRY, GET_REMOTE_COMMAND,                                
    GET_CPU_LIMIT, GET_RAM_LIMIT, GET_DISK_LIMIT,                          
    GET_BROADCAST_MSG, GET_REBOOT_TIME,                                    
    ADD_PAY_TYPE, ADD_PAY_NET, ADD_PAY_ADDR, ADD_PAY_HOLDER,               
    GET_RECEIPT                                                            
) = range(31)

GET_IRAN_NAME, GET_IRAN_IP, GET_IRAN_PORT, GET_IRAN_USER, GET_IRAN_PASS = range(200, 205)
GET_GROUP_ID_FOR_TOPICS = range(400, 401)[0]
GET_JSON_CONF, GET_SUB_LINK, GET_CONFIG_LINKS, GET_SUB_NAME, SELECT_CONFIG_TYPE = range(210, 215)
GET_CUSTOM_BIG_INTERVAL, GET_CUSTOM_BIG_SIZE, GET_CUSTOM_SMALL_SIZE = range(220, 223)
SELECT_ADD_METHOD, GET_LINEAR_DATA = range(100, 102)
ADMIN_GET_UID_FOR_REPORT = range(300)

# ==============================================================================
# 🔐 SECURITY & DATABASE
# ==============================================================================
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
            logger.error(f"Decryption failed: {e}")
            return ""

db = Database()
sec = Security()

# ==============================================================================
# 🚀 STARTUP & MENU HANDLERS
# ==============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id in USER_ACTIVE_TASKS:
        task = USER_ACTIVE_TASKS[user_id]
        if not task.done():
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass
        del USER_ACTIVE_TASKS[user_id]
    
    context.user_data.clear()
    await register_user_logic(update, context)

    if not cronjobs.IS_SYSTEM_INITIALIZED:
        asyncio.create_task(cronjobs.silent_update_monitor_agent())
        cronjobs.IS_SYSTEM_INITIALIZED = True

    await show_main_menu(update, context)
    return ConversationHandler.END

async def register_user_logic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    full_name = update.effective_user.full_name
    loop = asyncio.get_running_loop()
    args = context.args 
    inviter_id = 0

    existing_user = await loop.run_in_executor(None, db.get_user, user_id)
    is_new_user = False if existing_user else True

    if is_new_user and user_id != SUPER_ADMIN_ID and args and args[0].isdigit():
        possible_inviter = int(args[0])
        if possible_inviter != user_id:
            inviter_exists = await loop.run_in_executor(None, db.get_user, possible_inviter)
            if inviter_exists:
                inviter_id = possible_inviter

    await loop.run_in_executor(None, db.add_or_update_user, user_id, full_name, inviter_id)

    if user_id == SUPER_ADMIN_ID: return

    if is_new_user:
        try:
            admin_msg = f"🔔 **کاربر جدید!**\n👤 {full_name}\n🆔 `{user_id}`\n🔗 دعوت: `{inviter_id if inviter_id else 'مستقیم'}`"
            await context.bot.send_message(chat_id=SUPER_ADMIN_ID, text=admin_msg, parse_mode='Markdown')
        except: pass

        if inviter_id != 0:
            ok, new_lim, new_exp = await loop.run_in_executor(None, db.apply_referral_reward, inviter_id)
            if ok:
                try:
                    await context.bot.send_message(
                        chat_id=inviter_id,
                        text=(f"🎉 **تبریک! زیرمجموعه جدید:** {full_name}\n🎁 **پاداش:** +1 سرور (مجموع: {new_lim}) | +10 روز اعتبار")
                    )
                except: pass

        try:
            await update.message.reply_text(
                f"🎉 **سلام {full_name} عزیز، خوش اومدی!** \n\n✅ حساب شما ایجاد شد:\n🔹 **اعتبار اولیه:** 60 روز\n🔹 **ظرفیت سرور:** 2 عدد\n\nمی‌تونی با دعوت دوستانت، این محدودیت‌ها رو رایگان افزایش بدی! 🚀",
                parse_mode='Markdown'
            )
        except: pass

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    full_name = update.effective_user.full_name
    loop = asyncio.get_running_loop()
    
    has_access, msg = await loop.run_in_executor(None, db.check_access, user_id)
    if not has_access:
        msg_text = f"⛔️ دسترسی مسدود است: {msg}"
        if update.callback_query: await safe_edit_message(update, msg_text)
        else: await update.message.reply_text(msg_text)
        return

    remaining = f"{msg} روز" if isinstance(msg, int) else "♾ نامحدود"
    is_monitor_ready = await loop.run_in_executor(None, db.is_monitor_active)
    reply_markup = keyboard.main_menu_kb(user_id, is_monitor_ready, SUPER_ADMIN_ID)

    txt = (f"👋 **درود {full_name} عزیز، خوش آمدید!** 🌹\n🦇 **Sonar Radar Ultra Pro**\n➖➖➖➖➖➖➖➖➖➖\n✅ سیستم آماده‌سازی شد.\n📅 اعتبار شما: `{remaining}`\n🔰 گزینه مورد نظر را انتخاب کنید:")

    if update.callback_query:
        await safe_edit_message(update, txt, reply_markup=reply_markup)
    else:
        await update.message.reply_text(txt, reply_markup=reply_markup, parse_mode='Markdown')

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_main_menu(update, context)

async def user_profile_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        try: await update.callback_query.answer()
        except: pass
    
    uid = update.effective_user.id
    user = db.get_user(uid)

    if not user:
        await safe_edit_message(update, "❌ کاربر یافت نشد.")
        return

    try:
        join_date = datetime.strptime(user['added_date'], '%Y-%m-%d %H:%M:%S')
        j_join = jdatetime.date.fromgregorian(date=join_date.date())
        join_str = f"{j_join.day} {jdatetime.date.j_months_fa[j_join.month - 1]} {j_join.year}"
    except: join_str = "نامشخص"

    access, time_left = db.check_access(uid)
    if uid == SUPER_ADMIN_ID:
        sub_type = "👑 مدیریت کل (God Mode)"
        expiry_str = "♾ نامحدود"
    else:
        sub_type = "💎 پریمیوم (VIP)" if user['server_limit'] > 10 else "👤 عادی (Normal)"
        expiry_str = f"{time_left} روز مانده" if isinstance(time_left, int) else "نامحدود"

    servers = db.get_all_user_servers(uid)
    srv_count = len(servers)
    active_srv = sum(1 for s in servers if s['is_active'])

    txt = (f"👤 **پروفایل کاربری شما**\n➖➖➖➖➖➖➖➖➖➖\n🏷 **نام:** `{user['full_name']}`\n🆔 **آیدی عددی:** `{user['user_id']}`\n📅 **تاریخ عضویت:** `{join_str}`\n\n💳 **نوع اشتراک:** {sub_type}\n⏳ **اعتبار باقی‌مانده:** `{expiry_str}`\n🔢 **سقف مجاز سرور:** `{user['server_limit']} عدد`\n\n🖥 **وضعیت سرورها:**\n   ├ 🟢 فعال: `{active_srv}`\n   └ ⚪️ کل ثبت شده: `{srv_count}`")
    reply_markup = keyboard.user_profile_kb()
    await safe_edit_message(update, txt, reply_markup=reply_markup)

async def web_token_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: await update.callback_query.answer("🚧 پنل تحت وب در حال توسعه است.\nبه زودی این قابلیت فعال می‌شود!", show_alert=True)
    except: pass

# ==============================================================================
# 👑 ADMIN PANEL HANDLERS
# ==============================================================================
async def admin_backup_get(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت بکاپ دستی Postgres"""
    try: await update.callback_query.answer("⏳ در حال تهیه بکاپ...")
    except: pass

    timestamp = get_tehran_datetime().strftime("%Y-%m-%d_%H-%M")
    backup_file = f"manual_backup_{timestamp}.sql"

    try:
        env = os.environ.copy()
        env['PGPASSWORD'] = DB_CONFIG['password']

        cmd = [
            "pg_dump", "-h", DB_CONFIG['host'], "-U", DB_CONFIG['user'],
            "-d", DB_CONFIG['dbname'], "-f", backup_file
        ]
        
        proc = await asyncio.create_subprocess_exec(*cmd, env=env)
        await proc.wait()

        if proc.returncode == 0:
            await update.callback_query.message.reply_document(
                document=open(backup_file, 'rb'),
                caption=f"📦 Manual Backup: {get_jalali_str()}"
            )
        else:
            await update.callback_query.message.reply_text("❌ خطا در تهیه بکاپ.")
            
    except Exception as e:
        await update.callback_query.message.reply_text(f"❌ خطا: {e}")
    finally:
        if os.path.exists(backup_file): os.remove(backup_file)
async def admin_backup_restore_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_edit_message(update, "⚠️ **هشدار:** با آپلود فایل جدید، دیتابیس فعلی حذف و جایگزین می‌شود.\n\n📂 **فایل .db خود را ارسال کنید:**", reply_markup=keyboard.get_cancel_markup())
    return ADMIN_RESTORE_DB

async def admin_backup_restore_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بازگردانی دیتابیس Postgres از فایل SQL"""
    doc = update.message.document
    # چک کردن پسوند فایل (باید sql باشد نه db)
    if not (doc.file_name.endswith('.sql') or doc.file_name.endswith('.txt')):
        await update.message.reply_text("❌ فرمت فایل نامعتبر است. لطفاً فایل `.sql` ارسال کنید.")
        return ADMIN_RESTORE_DB

    temp_name = "temp_restore.sql"
    f = await doc.get_file()
    await f.download_to_drive(temp_name)

    msg = await update.message.reply_text("⏳ **در حال بازنشانی دیتابیس...**\n(این عملیات ممکن است کمی طول بکشد)")

    try:
        env = os.environ.copy()
        env['PGPASSWORD'] = DB_CONFIG['password']

        # دستور بازگردانی (psql)
        # نکته: دیتابیس قبلی پاک نمی‌شود، بلکه روی آن نوشته می‌شود. 
        # اگر می‌خواهید کامل جایگزین شود، باید ابتدا جداول را DROP کنید که کمی پیچیده است.
        # این دستور استاندارد ریستور است:
        cmd = [
            "psql", "-h", DB_CONFIG['host'], "-U", DB_CONFIG['user'],
            "-d", DB_CONFIG['dbname'], "-f", temp_name
        ]

        proc = await asyncio.create_subprocess_exec(*cmd, env=env)
        await proc.wait()

        if proc.returncode == 0:
            await msg.edit_text("✅ **دیتابیس با موفقیت بازنشانی شد.**\nربات اکنون با داده‌های جدید کار می‌کند.")
            await start(update, context)
        else:
            await msg.edit_text("❌ خطا در اجرای دستور psql.")

    except Exception as e:
        await msg.edit_text(f"❌ خطا در بازنشانی: {e}")
    finally:
        if os.path.exists(temp_name): os.remove(temp_name)
    
    return ConversationHandler.END
async def admin_key_backup_get(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not os.path.exists(KEY_FILE):
        try: await update.callback_query.answer("❌ فایل کلید یافت نشد!", show_alert=True)
        except: pass
        return
    await update.callback_query.message.reply_document(document=open(KEY_FILE, 'rb'), caption="🔑 **فایل کلید امنیتی (Secret Key)**\n⚠️ این فایل را برای روز مبادا نگه دارید.")

async def admin_key_restore_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_edit_message(update, "🗝 **لطفاً فایل secret.key را ارسال کنید:**", reply_markup=keyboard.get_cancel_markup())
    return ADMIN_RESTORE_KEY

async def admin_key_restore_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    f = await update.message.document.get_file()
    await f.download_to_drive("temp_key.key")
    if os.path.exists(KEY_FILE): os.remove(KEY_FILE)
    os.rename("temp_key.key", KEY_FILE)
    global sec
    sec = Security()
    await update.message.reply_text("✅ **کلید امنیتی بازیابی شد!**")
    await start(update, context)
    return ConversationHandler.END

# ==============================================================================
# 💳 PAYMENT SETTINGS (ADMIN)
# ==============================================================================
async def admin_payment_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    methods = db.get_payment_methods()
    txt = "💳 **مدیریت روش‌های پرداخت**\n\nلیست روش‌های فعال:\n" + ("❌ هیچ روش پرداختی تعریف نشده است." if not methods else "")
    reply_markup = keyboard.admin_pay_settings_kb(methods)
    if update.callback_query:
        await safe_edit_message(update, txt + "\n\n👇 برای حذف روی دکمه‌ها بزنید.", reply_markup=reply_markup)

async def delete_payment_method_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    p_id = int(update.callback_query.data.split('_')[3])
    db.delete_payment_method(p_id)
    await update.callback_query.answer("🗑 حذف شد.")
    await admin_payment_settings(update, context)

async def add_pay_method_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    p_type = update.callback_query.data.split('_')[3]
    context.user_data['new_pay_type'] = p_type
    msg = "🏦 **نام بانک را وارد کنید:**\n(مثال: بانک ملت)" if p_type == 'card' else "💎 **نام ارز و شبکه را وارد کنید:**\n(مثال: USDT - TRC20 یا TON)"
    await safe_edit_message(update, msg, reply_markup=keyboard.get_cancel_markup())
    return ADD_PAY_NET

async def get_pay_network(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_pay_net'] = update.message.text
    p_type = context.user_data['new_pay_type']
    msg = "🔢 **شماره کارت را وارد کنید:**" if p_type == 'card' else "🔗 **آدرس ولت (Wallet Address) را ارسال کنید:**"
    await update.message.reply_text(msg, reply_markup=keyboard.get_cancel_markup())
    return ADD_PAY_ADDR

async def get_pay_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_pay_addr'] = update.message.text
    msg = "👤 **نام صاحب حساب را وارد کنید:**" if context.user_data['new_pay_type'] == 'card' else "📝 **توضیحات کوتاه یا نام ولت:**\n(مثال: ولت اصلی)"
    await update.message.reply_text(msg, reply_markup=keyboard.get_cancel_markup())
    return ADD_PAY_HOLDER

async def get_pay_holder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    holder = update.message.text
    data = context.user_data
    db.add_payment_method(data['new_pay_type'], data['new_pay_net'], data['new_pay_addr'], holder)
    await update.message.reply_text("✅ **روش پرداخت با موفقیت اضافه شد.**")
    kb = [[InlineKeyboardButton("بازگشت به مدیریت پرداخت", callback_data='admin_pay_settings')]]
    await update.message.reply_text("جهت مشاهده لیست، دکمه زیر را بزنید:", reply_markup=InlineKeyboardMarkup(kb))
    return ConversationHandler.END

# ==============================================================================
# 🛠 SERVER & GROUP MANAGEMENT
# ==============================================================================
async def groups_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    groups = db.get_user_groups(update.effective_user.id)
    reply_markup = keyboard.groups_menu_kb(groups)
    await safe_edit_message(update, "📂 Groups:", reply_markup=reply_markup)

async def add_group_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_edit_message(update, "📝 Name:", reply_markup=keyboard.get_cancel_markup())
    return GET_GROUP_NAME

async def get_group_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.add_group(update.effective_user.id, update.message.text)
    await start(update, context)
    return ConversationHandler.END

async def delete_group_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.delete_group(int(update.callback_query.data.split('_')[1]), update.effective_user.id)
    await groups_menu(update, context)

async def add_server_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    srv_count = len(db.get_all_user_servers(update.effective_user.id))
    if update.effective_user.id != SUPER_ADMIN_ID and srv_count >= user['server_limit']:
        await update.effective_message.reply_text("⛔️ **شما به سقف مجاز افزودن سرور رسیده‌اید.**")
        return ConversationHandler.END
    await safe_edit_message(update, "🏷 **نام سرور را وارد کنید:**", reply_markup=keyboard.get_cancel_markup())
    return GET_NAME

async def add_server_start_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    srv_count = len(db.get_all_user_servers(update.effective_user.id))
    if update.effective_user.id != SUPER_ADMIN_ID and srv_count >= user['server_limit']:
        await safe_edit_message(update, "⛔️ **شما به سقف مجاز افزودن سرور رسیده‌اید.**")
        return ConversationHandler.END
    reply_markup = keyboard.add_server_method_kb()
    txt = "➕ **افزودن سرور جدید**\n\nلطفاً روش مورد نظر خود را انتخاب کنید:\n\n1️⃣ **مرحله به مرحله:** ربات سوال می‌پرسد و شما پاسخ می‌دهید.\n2️⃣ **سریع (خطی):** تمام اطلاعات را در یک پیام می‌فرستید (مناسب برای افزودن همزمان چند سرور)."
    if update.callback_query: await safe_edit_message(update, txt, reply_markup=reply_markup)
    else: await update.message.reply_text(txt, reply_markup=reply_markup)
    return SELECT_ADD_METHOD

async def add_server_step_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("🏷 **نام سرور را وارد کنید:**", reply_markup=keyboard.get_cancel_markup())
    return GET_NAME

async def add_server_linear_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    txt = "⚡️ **افزودن سریع سرورها**\n\nلطفاً مشخصات سرورها را به صورت **5 خطی** ارسال کنید.\nهر سرور باید دقیقاً در 5 خط زیر هم باشد:\n1. نام سرور\n2. آی‌پی\n3. پورت\n4. یوزرنیم\n5. پسورد\n\n⚠️ **نکته:** اگر چند سرور دارید، بلافاصله بعد از پسورد اولی، اطلاعات سرور دوم را شروع کنید.\n\n💡 **مثال:**\n`Server A`\n`192.168.1.1`\n`22`\n`root`\n`Pass123`\n`Server B`\n`45.33.22.11`\n`2244`\n`admin`\n`Secr3t`\n\n👇 اطلاعات را ارسال کنید:"
    await update.callback_query.message.reply_text(txt, reply_markup=keyboard.get_cancel_markup(), parse_mode='Markdown')
    return GET_LINEAR_DATA
async def process_linear_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش متن خطی با فرمت ۵ خطی (همراه با سیستم ضد بلاک)"""
    text = update.message.text
    # حذف خطوط خالی اضافی
    lines = [line.strip() for line in text.split('\n') if line.strip()]

    uid = update.effective_user.id
    user = db.get_user(uid)
    limit = user['server_limit']
    current_count = len(db.get_all_user_servers(uid))

    success = 0
    failed = 0
    report = []

    msg = await update.message.reply_text("⏳ **در حال پردازش، تست اتصال و ایمن‌سازی...**")

    # بررسی فرمت
    if len(lines) % 5 != 0:
        await msg.edit_text(
            f"❌ **فرمت ارسال اشتباه است!**\n\n"
            f"تعداد خطوط باید مضربی از ۵ باشد (نام، آی‌پی، پورت، یوزر، پسورد).\n"
            f"شما {len(lines)} خط فرستادید.\n\n"
            "لطفاً اصلاح کنید و مجدد ارسال نمایید."
        )
        return GET_LINEAR_DATA

    loop = asyncio.get_running_loop()

    # 1. دریافت آی‌پی ربات (یکبار برای همه)
    bot_public_ip = await loop.run_in_executor(None, ServerMonitor.get_bot_public_ip)

    # پردازش ۵ خط به ۵ خط
    for i in range(0, len(lines), 5):
        if uid != SUPER_ADMIN_ID and (current_count + success) >= limit:
            report.append(f"⛔️ محدودیت پر شد! (سرور {lines[i]} نادیده گرفته شد)")
            failed += 1
            continue

        name = lines[i]
        ip = lines[i + 1]
        port_str = lines[i + 2]
        username = lines[i + 3]
        password = lines[i + 4]

        if not port_str.isdigit():
            report.append(f"⚠️ پورت نامعتبر برای {name}: `{port_str}`")
            failed += 1
            continue

        port = int(port_str)

        # تست اتصال
        res = await loop.run_in_executor(
            None, ServerMonitor.check_full_stats, ip, port, username, password
        )

        if res['status'] == 'Online':
            try:
                # ذخیره در دیتابیس
                data = {
                    'name': name, 'ip': ip, 'port': port,
                    'username': username, 'password': sec.encrypt(password),
                    'expiry_date': None
                }
                db.add_server(uid, 0, data)

                # ✅ اجرای سیستم ضد بلاک (Anti-Block)
                if bot_public_ip:
                    # تعریف تابع برای اجرا در ترد جداگانه
                    def run_whitelist():
                        ServerMonitor.whitelist_bot_ip(ip, port, username, password, bot_public_ip)
                    
                    # اجرا در پس‌زمینه (Fire & Forget) تا سرعت افزودن کم نشود
                    asyncio.create_task(loop.run_in_executor(None, run_whitelist))

                report.append(f"✅ **{name}**: افزوده و ایمن‌سازی شد.")
                success += 1
            except Exception as e:
                report.append(f"❌ خطا در ذخیره {name}: {e}")
                failed += 1
        else:
            report.append(f"🔴 عدم اتصال {name}: `{res['error']}`")
            failed += 1

    final_txt = (
            f"📊 **نتیجه عملیات:**\n"
            f"✅ موفق: `{success}` | ❌ ناموفق: `{failed}`\n"
            f"➖➖➖➖➖➖➖➖\n" +
            "\n".join(report)
    )

    await msg.edit_text(final_txt, parse_mode='Markdown')
    await asyncio.sleep(3)
    await start(update, context)
    return ConversationHandler.END

async def get_srv_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['srv'] = {'name': update.message.text}
    await update.message.reply_text("🌐 **آدرس IP سرور را وارد کنید:**", reply_markup=keyboard.get_cancel_markup(),
                                    parse_mode='Markdown')
    return GET_IP


async def get_srv_ip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['srv']['ip'] = update.message.text
    await update.message.reply_text("🔌 **پورت SSH را وارد کنید:**", reply_markup=keyboard.get_cancel_markup(),
                                    parse_mode='Markdown')
    return GET_PORT


async def get_srv_port(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['srv']['port'] = int(update.message.text)
    except:
        await update.message.reply_text("❌ فقط عدد وارد کنید.")
        return GET_PORT
    await update.message.reply_text("👤 **نام کاربری (Username) را وارد کنید:**", reply_markup=keyboard.get_cancel_markup(),
                                    parse_mode='Markdown')
    return GET_USER


async def get_srv_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['srv']['username'] = update.message.text
    await update.message.reply_text("🔑 **رمز عبور (Password) را وارد کنید:**", reply_markup=keyboard.get_cancel_markup(),
                                    parse_mode='Markdown')
    return GET_PASS


async def get_srv_pass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['srv']['password'] = sec.encrypt(update.message.text)
    await update.message.reply_text(
        "📅 **مهلت انقضای سرور چند روز دیگر است؟**\n\n"
        "🔢 عدد وارد کنید (مثلاً `30` برای یک ماه)\n"
        "یا عدد `0` را وارد کنید اگر نامحدود است.",
        reply_markup=keyboard.get_cancel_markup(), parse_mode='Markdown'
    )
    return GET_EXPIRY


async def get_srv_expiry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        days = int(update.message.text)
        if days > 0:
            expiry_dt = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')
            context.user_data['srv']['expiry_date'] = expiry_dt
            msg = f"✅ تاریخ انقضا تنظیم شد: {days} روز دیگر."
        else:
            context.user_data['srv']['expiry_date'] = None
            msg = "♾ سرور به عنوان نامحدود ثبت شد."
    except:
        await update.message.reply_text("❌ لطفاً فقط عدد وارد کنید (مثلا 30).")
        return GET_EXPIRY

    # استفاده از ماژول کیبورد (برای select_group_kb که لیست برمی‌گرداند)
    group_kb_list = await get_group_keyboard(update.effective_user.id)
    
    await update.message.reply_text(f"{msg}\n\n📂 **حالا سرور در کدام پوشه ذخیره شود؟**",
                                    reply_markup=InlineKeyboardMarkup(group_kb_list),
                                    parse_mode='Markdown')
    return SELECT_GROUP


async def get_group_keyboard(uid):
    groups = db.get_user_groups(uid)
    return keyboard.select_group_kb(groups)


async def select_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ذخیره نهایی سرور و اجرای وایت‌لیست"""
    if update.callback_query.data == 'cancel_flow': return await cancel_handler_func(update, context)
    
    await safe_edit_message(update, "⚡️ **در حال تست اتصال و ایمن‌سازی سرور...**")
    
    data = context.user_data['srv']
    loop = asyncio.get_running_loop()
    
    # تست اتصال
    res = await loop.run_in_executor(None, ServerMonitor.check_full_stats, data['ip'], data['port'], data['username'], sec.decrypt(data['password']))
    
    if res['status'] == 'Online':
        try:
            # ذخیره در دیتابیس
            db.add_server(update.effective_user.id, int(update.callback_query.data), data)
            
            # ✅ اجرای سیستم ضد بلاک (Anti-Block)
            try:
                bot_ip = await loop.run_in_executor(None, ServerMonitor.get_bot_public_ip)
                if bot_ip:
                    # اجرا در پس‌زمینه
                    def run_whitelist():
                        ServerMonitor.whitelist_bot_ip(data['ip'], data['port'], data['username'], sec.decrypt(data['password']), bot_ip)
                    
                    asyncio.create_task(loop.run_in_executor(None, run_whitelist))
            except Exception as e:
                logger.error(f"Whitelist Error on Add: {e}")

            await update.callback_query.message.reply_text("✅ **اتصال موفق! سرور ذخیره و وایت‌لیست شد.**", parse_mode='Markdown')
        except Exception as e:
            await update.callback_query.message.reply_text(f"❌ خطا در ذخیره: {e}")
    else:
        await update.callback_query.message.reply_text(f"❌ **عدم اتصال به سرور!**\n\n⚠️ خطا: `{res['error']}`", parse_mode='Markdown')
        
    await start(update, context)
    return ConversationHandler.END

async def list_groups_for_servers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.callback_query.answer()
    except:
        pass
    groups = db.get_user_groups(update.effective_user.id)
    
    # استفاده از ماژول کیبورد
    reply_markup = keyboard.group_selection_kb(groups)
    
    await safe_edit_message(update, "🗂 **پوشه مورد نظر را انتخاب کنید:**", reply_markup=reply_markup)


async def show_servers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.callback_query.answer()
    except:
        pass
    uid, data = update.effective_user.id, update.callback_query.data
    servers = db.get_all_user_servers(uid) if data == 'list_all' else db.get_servers_by_group(uid, int(
        data.split('_')[1]))
    if not servers:
        try:
            await update.callback_query.answer("⚠️ این پوشه خالی است!", show_alert=True)
        except:
            pass
        return
    
    reply_markup = keyboard.server_list_kb(servers)
    
    await safe_edit_message(update, "🖥 **لیست سرورها:**", reply_markup=reply_markup)
# ==============================================================================
# 📊 MONITORING & SERVER ACTIONS
# ==============================================================================
async def dashboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await status_dashboard(update, context)

async def status_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """داشبورد اصلی با رابط کاربری گرافیکی و تفکیک شده"""
    if update.callback_query:
        try: await update.callback_query.answer()
        except: pass
    
    user = update.effective_user
    j_date = get_jalali_str()
    
    txt = (
        f"📊 **داشبورد مدیریتی سونار**\n"
        f"👤 کاربر: {user.full_name}\n"
        f"📅 تاریخ: `{j_date}`\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"یکی از بخش‌های زیر را برای مشاهده وضعیت انتخاب کنید:"
    )
    
    # استفاده از ماژول کیبورد
    reply_markup = keyboard.dashboard_main_kb()
    
    await safe_edit_message(update, txt, reply_markup=reply_markup)

# این تابع جدید برای نمایش وضعیت سرورهاست (جایگزین لاجیک قبلی در داشبورد)
async def show_server_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = update.effective_user.id
    
    await safe_edit_message(update, "🔄 **در حال دریافت وضعیت سرورها...**")
    
    servers = db.get_all_user_servers(uid)
    if not servers:
        await safe_edit_message(update, "❌ هیچ سروری ثبت نشده است.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='status_dashboard')]]))
        return

    loop = asyncio.get_running_loop()
    tasks = []
    for s in servers:
        if s['is_active']:
            # 👇 اصلاح شد: استفاده از StatsManager
            tasks.append(loop.run_in_executor(None, StatsManager.check_full_stats, s['ip'], s['port'], s['username'], sec.decrypt(s['password'])))
        else:
            async def fake(): return {'status': 'Disabled'}
            tasks.append(fake())
            
    results = await asyncio.gather(*tasks)
    
    txt = f"🖥 **وضعیت سرورهای شما**\n➖➖➖➖➖➖➖➖➖➖\n\n"
    active_count = 0
    
    for i, res in enumerate(results):
        final_res = res if isinstance(res, dict) else await res
        srv = servers[i]
        
        if final_res.get('status') == 'Online':
            active_count += 1
            # 👇 اصلاح شد: استفاده از StatsManager
            cpu_bar = StatsManager.make_bar(final_res['cpu'], 5)
            ram_bar = StatsManager.make_bar(final_res['ram'], 5)
            txt += (
                f"🟢 **{srv['name']}**\n"
                f"   🧠 CPU: `{cpu_bar}` {final_res['cpu']}%\n"
                f"   💾 RAM: `{ram_bar}` {final_res['ram']}%\n"
                f"   📡 Traf: `{final_res['traffic_gb']} GB`\n"
                f"────────────────\n"
            )
        else:
             txt += f"🔴 **{srv['name']}** ⇽ ⛔️ OFFLINE\n────────────────\n"

    # استفاده از ماژول کیبورد
    reply_markup = keyboard.server_stats_kb()
    
    await safe_edit_message(update, txt, reply_markup=reply_markup)

async def server_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, custom_sid=None):
    if update.callback_query:
        try:
            await update.callback_query.answer()
        except:
            pass

    if custom_sid:
        sid = custom_sid
    elif update.callback_query:
        sid = update.callback_query.data.split('_')[1]
    else:
        return

    srv = db.get_server_by_id(sid)
    if not srv: return

    await safe_edit_message(update, f"⚡️ **در حال پردازش اطلاعات سرور {srv['name']}...**")

    user_id = update.effective_user.id
    user = db.get_user(user_id)
    is_premium = True if user['plan_type'] == 1 or user_id == SUPER_ADMIN_ID else False

    # 👇 اصلاح شد: استفاده از StatsManager
    res = await asyncio.get_running_loop().run_in_executor(
        None, StatsManager.check_full_stats, srv['ip'], srv['port'], srv['username'], sec.decrypt(srv['password'])
    )

    expiry_display = "♾ **نامحدود (همیشگی)**"
    status_expiry = "✅"

    if srv['expiry_date']:
        try:
            exp_date_obj = datetime.strptime(srv['expiry_date'], '%Y-%m-%d')
            today = datetime.now().date()
            days_left = (exp_date_obj.date() - today).days
            j_date = jdatetime.date.fromgregorian(date=exp_date_obj)
            persian_months = {1: 'فروردین', 2: 'اردیبهشت', 3: 'خرداد', 4: 'تیر', 5: 'مرداد', 6: 'شهریور', 7: 'مهر',
                              8: 'آبان', 9: 'آذر', 10: 'دی', 11: 'بهمن', 12: 'اسفند'}
            expiry_display = f"{j_date.day} {persian_months[j_date.month]} {j_date.year}"

            if days_left < 0:
                expiry_display += f"\n   🚩 **( {abs(days_left)} روز گذشته - منقضی شده 🔴 )**"
                status_expiry = "🔴"
            elif days_left == 0:
                expiry_display += "\n   ⚠️ **( امروز منقضی می‌شود! )**"
                status_expiry = "🟠"
            elif days_left <= 3:
                expiry_display += f"\n   ⚠️ **( تنها {days_left} روز باقی مانده )**"
                status_expiry = "🟡"
            else:
                expiry_display += f"\n   ⏳ **( {days_left} روز باقی مانده )**"
                status_expiry = "🟢"
        except:
            expiry_display = f"{srv['expiry_date']} (خطا در محاسبه)"

    uptime_display = "⚠️ نامعلوم"
    if res.get('uptime_sec', 0) > 0:
        total_seconds = int(res['uptime_sec'])
        total_hours = total_seconds // 3600
        remaining_minutes = (total_seconds % 3600) // 60
        equiv_days = total_seconds // 86400
        uptime_display = (
            f"🕰 **{total_hours}** ساعت **{remaining_minutes}** دقیقه\n"
            f"   ╰ (معادل **{equiv_days}** روز فعالیت 🔥)"
        )

    # استفاده از ماژول کیبورد
    reply_markup = keyboard.server_detail_kb(sid, srv['ip'], is_premium)

    if res['status'] == 'Online':
        db.update_status(sid, "Online")
        cpu_emoji = "🟢" if res['cpu'] < 50 else "🟡" if res['cpu'] < 80 else "🔴"
        ram_emoji = "🟢" if res['ram'] < 50 else "🟡" if res['ram'] < 80 else "🔴"
        disk_emoji = "💿" if res['disk'] < 80 else "⚠️"

        txt = (
            f"🟢 **{srv['name']}** `[آنلاین]`\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🎫 **اشتراک:** {status_expiry}\n"
            f"📅 `{expiry_display}`\n\n"
            f"🔌 **زمان فعال بودن:**\n"
            f"{uptime_display}\n\n"
            f"🌐 **IP:** `{srv['ip']}`\n"
            f"📡 **ترافیک:** `{res['traffic_gb']} GB`\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📊 **منابع:**\n\n"
            f"{cpu_emoji} **CPU:** `{res['cpu']}%`\n"
            f"`{StatsManager.make_bar(res['cpu'], length=15)}`\n\n"
            f"{ram_emoji} **RAM:** `{res['ram']}%`\n"
            f"`{StatsManager.make_bar(res['ram'], length=15)}`\n\n"
            f"{disk_emoji} **Disk:** `{res['disk']}%`\n"
            f"`{StatsManager.make_bar(res['disk'], length=15)}`"
        )
    else:
        db.update_status(sid, "Offline")
        txt = (
            f"🔴 **{srv['name']}** `[آفلاین]`\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ **سرور در دسترس نیست!**\n\n"
            f"🔍 **عیب‌یابی:**\n"
            f"1. آیا سرور خاموش است؟\n"
            f"2. آیا IP ربات مسدود شده؟\n"
            f"3. آیا پورت SSH تغییر کرده است؟\n\n"
            f"📅 **انقضا:**\n`{expiry_display}`\n\n"
            f"❌ **خطا:**\n`{res['error']}`"
        )

    await safe_edit_message(update, txt, reply_markup=reply_markup)

async def server_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data
    parts = data.split('_')
    act, sid = parts[1], parts[2]

    srv = db.get_server_by_id(sid)
    if not srv:
        try:
            await update.callback_query.answer("❌ سرور یافت نشد!", show_alert=True)
        except:
            pass
        return

    uid = update.effective_user.id
    user = db.get_user(uid)
    is_premium = True if user['plan_type'] == 1 or uid == SUPER_ADMIN_ID else False

    LOCKED_FEATURES = ['installscript']

    if act in LOCKED_FEATURES and not is_premium:
        try:
            await update.callback_query.answer("🔒 این قابلیت مخصوص کاربران پریمیوم است!", show_alert=True)
        except:
            pass
        return

    if srv['password']:
        real_pass = sec.decrypt(srv['password'])
    else:
        real_pass = ""

    loop = asyncio.get_running_loop()

    if act == 'del':
        db.delete_server(sid, update.effective_user.id)
        try:
            await update.callback_query.answer("✅ سرور با موفقیت حذف شد.")
        except:
            pass
        await list_groups_for_servers(update, context)

    elif act == 'reboot':
        try:
            await update.callback_query.answer("⚠️ دستور ریبوت ارسال شد.")
        except:
            pass
        # عملیات اجرایی همچنان در ServerMonitor (Core) باقی می‌ماند
        asyncio.create_task(run_background_ssh_task(
            context, update.effective_chat.id,
            ServerMonitor.run_remote_command, srv['ip'], srv['port'], srv['username'], real_pass, "reboot"
        ))

    elif act == 'editexpiry':
        await edit_expiry_start(update, context)

    elif act == 'fullreport':
        wait_msg = await update.callback_query.message.reply_text(
            "⏳ **در حال آنالیز جامع وضعیت سرور...**\n\n"
            "1️⃣ استعلام دیتاسنتر...\n"
            "2️⃣ پینگ جهانی (۱۰ ثانیه زمان می‌برد)..."
        )
        # 👇 اصلاح شد: استفاده از StatsManager برای اطلاعات آماری
        task_dc = loop.run_in_executor(None, StatsManager.get_datacenter_info, srv['ip'])
        task_ch = loop.run_in_executor(None, StatsManager.check_host_api, srv['ip'])

        (dc_ok, dc_data), (ch_ok, ch_data) = await asyncio.gather(task_dc, task_ch)

        if dc_ok:
            infra_txt = (
                f"🏢 **زیرساخت (Infrastructure):**\n"
                f"➖➖➖➖➖➖➖➖➖➖\n"
                f"🏳️ **کشور:** {dc_data['country_name']} ({dc_data['country_code2']})\n"
                f"🏢 **دیتاسنتر:** `{dc_data['isp']}`\n"
                f"🔢 **آی‌پی:** `{dc_data['ip_number']}`\n"
            )
        else:
            infra_txt = f"❌ خطا در دریافت اطلاعات دیتاسنتر: {dc_data}\n"

        if ch_ok:
            # 👇 اصلاح شد: استفاده از StatsManager
            ping_txt = StatsManager.format_full_global_results(ch_data)
        else:
            ping_txt = f"❌ خطا در Check-Host API: {ch_data}"

        final_report = (
            f"📊 **گزارش جامع سرور: {srv['name']}**\n"
            f"📅 {get_jalali_str()}\n\n"
            f"{infra_txt}\n"
            f"🌍 **وضعیت پینگ جهانی:**\n"
            f"➖➖➖➖➖➖➖➖➖➖\n"
            f"{ping_txt}"
        )
        await wait_msg.delete()
        await update.callback_query.message.reply_text(final_report, parse_mode='Markdown')

    elif act == 'chart':
        await update.callback_query.message.reply_text("📊 **در حال ترسیم نمودار...**")
        stats = await loop.run_in_executor(None, db.get_server_stats, sid)
        if not stats:
            await update.callback_query.message.reply_text("❌ داده‌ای برای رسم نمودار موجود نیست.")
            return
        # 👇 اصلاح شد: استفاده از StatsManager
        photo = await loop.run_in_executor(None, StatsManager.generate_plot, srv['name'], stats)
        if photo:
            await update.callback_query.message.reply_photo(photo=photo, caption=f"📊 مصرف منابع: **{srv['name']}**")
        else:
            await update.callback_query.message.reply_text("❌ خطا در تولید تصویر نمودار.")

    elif act == 'datacenter':
        await update.callback_query.message.reply_text("🔍 **در حال استعلام...**")
        # 👇 اصلاح شد: استفاده از StatsManager
        ok, data = await loop.run_in_executor(None, StatsManager.get_datacenter_info, srv['ip'])
        if ok:
            txt = (
                f"🏢 **مشخصات دیتاسنتر:**\n"
                f"➖➖➖➖➖➖➖➖➖➖\n"
                f"🖥 **آی‌پی:** `{data['ip']}`\n"
                f"🌍 **کشور:** {data['country_name']} ({data['country_code2']})\n"
                f"🏢 **کمپانی:** `{data['isp']}`\n"
                f"✅ **وضعیت:** {data['response_message']}"
            )
            await update.callback_query.message.reply_text(txt, parse_mode='Markdown')
        else:
            await update.callback_query.message.reply_text(f"❌ خطا: `{data}`", parse_mode='Markdown')

    elif act == 'checkhost':
        await update.callback_query.message.reply_text("🌍 **در حال دریافت گزارش Check-Host...**")
        # 👇 اصلاح شد: استفاده از StatsManager
        ok, data = await loop.run_in_executor(None, StatsManager.check_host_api, parts[3])
        report = StatsManager.format_check_host_results(data) if ok else f"❌ خطا: {data}"
        await update.callback_query.message.reply_text(report, parse_mode='Markdown')

    elif act == 'speedtest':
        await update.callback_query.message.reply_text(
            "🚀 **تست سرعت آغاز شد...**\n(نتیجه پس از پایان ارسال می‌شود، می‌توانید به کارهای دیگر برسید)")
        # عملیات اجرایی همچنان در ServerMonitor (Core) باقی می‌ماند
        asyncio.create_task(run_background_ssh_task(
            context, update.effective_chat.id,
            ServerMonitor.run_speedtest, srv['ip'], srv['port'], srv['username'], real_pass
        ))

    elif act == 'installspeed':
        await update.callback_query.message.reply_text("📥 **نصب ابزار Speedtest در پس‌زمینه آغاز شد...**")
        asyncio.create_task(run_background_ssh_task(
            context, update.effective_chat.id,
            ServerMonitor.install_speedtest, srv['ip'], srv['port'], srv['username'], real_pass
        ))

    elif act == 'repoupdate':
        await update.callback_query.message.reply_text(
            "📦 **آپدیت مخازن در حال انجام است...**\n(لطفاً صبور باشید، نتیجه ارسال می‌شود)")
        asyncio.create_task(run_background_ssh_task(
            context, update.effective_chat.id,
            ServerMonitor.repo_update, srv['ip'], srv['port'], srv['username'], real_pass
        ))

    elif act == 'fullupdate':
        await update.callback_query.message.reply_text(
            "💎 **آپدیت کامل سیستم آغاز شد!**\n⚠️ این عملیات ممکن است ۱۰ تا ۲۰ دقیقه زمان ببرد.\nنتیجه پس از پایان ارسال خواهد شد.")
        asyncio.create_task(run_background_ssh_task(
            context, update.effective_chat.id,
            ServerMonitor.full_system_update, srv['ip'], srv['port'], srv['username'], real_pass
        ))

    elif act == 'clearcache':
        try:
            await update.callback_query.answer("🧹 کش رم پاکسازی شد.")
        except:
            pass
        await loop.run_in_executor(None, ServerMonitor.clear_cache, srv['ip'], srv['port'], srv['username'], real_pass)
        await server_detail(update, context)

    elif act == 'cleandisk':
        await update.callback_query.message.reply_text(
            "🧹 **پاکسازی دیسک آغاز شد...**\n"
            "این عملیات شامل حذف:\n"
            "- پکیج‌های بلااستفاده (Autoremove)\n"
            "- کش پکیج‌ها (Apt Clean)\n"
            "- لاگ‌های قدیمی (Journalctl)\n"
            "- فایل‌های موقت (Tmp)\n\n"
            "⏳ لطفاً صبر کنید..."
        )
        ok, result = await loop.run_in_executor(None, ServerMonitor.clean_disk_space, srv['ip'], srv['port'],
                                                srv['username'], real_pass)
        if ok:
            await update.callback_query.message.reply_text(
                f"✅ **پاکسازی با موفقیت انجام شد.**\n💾 فضای آزاد شده: `{result:.2f} MB`", parse_mode='Markdown')
        else:
            await update.callback_query.message.reply_text(f"❌ خطا در پاکسازی:\n{result}")
        await server_detail(update, context)

    elif act == 'dns':
        # استفاده از ماژول کیبورد
        reply_markup = keyboard.dns_selection_kb(sid)
        
        await safe_edit_message(update,
                                "⚙️ **تنظیم DNS سرور:**\nلطفاً پرووایدر مورد نظر را انتخاب کنید.\n(پس از انتخاب، اتصال اینترنت سرور با DNS جدید برقرار می‌شود)",
                                reply_markup=reply_markup)

    elif act == 'locked_terminal':
        try:
            await update.callback_query.answer("🔒 ترمینال مخصوص کاربران پریمیوم است.\nبرای دسترسی ارتقا دهید.",
                                               show_alert=True)
        except:
            pass

    elif act == 'installscript':
        try:
            await update.callback_query.answer("🚧 این بخش در حال توسعه است!", show_alert=True)
        except:
            pass
async def set_config_cron_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ذخیره تنظیمات زمان‌بندی کانفیگ"""
    query = update.callback_query
    minutes = query.data.split('_')[1]
    
    db.set_setting(update.effective_user.id, 'config_report_interval', minutes)
    
    msg = "✅ گزارش کانفیگ غیرفعال شد." if minutes == '0' else f"✅ تنظیم شد: هر {minutes} دقیقه."
    try: await query.answer(msg, show_alert=True)
    except: pass
    
    await config_cron_menu(update, context)

async def set_cron_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.set_setting(update.effective_user.id, 'report_interval', int(update.callback_query.data.split('_')[1]))
    try:
        await update.callback_query.answer("ذخیره شد.")
    except:
        pass
    await settings_cron_menu(update, context)


async def resource_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """منوی تنظیم آستانه مصرف منابع"""
    uid = update.effective_user.id
    if update.callback_query:
        try:
            await update.callback_query.answer()
        except:
            pass

    cpu_limit = db.get_setting(uid, 'cpu_threshold') or '80'
    ram_limit = db.get_setting(uid, 'ram_threshold') or '80'
    disk_limit = db.get_setting(uid, 'disk_threshold') or '90'

    txt = (
        "🎚 **تنظیم آستانه حساسیت (Thresholds)**\n"
        "➖➖➖➖➖➖➖➖➖➖\n"
        "اگر مصرف منابع سرور از مقادیر زیر بیشتر شود، ربات هشدار می‌دهد.\n\n"
        f"🧠 **حداکثر CPU مجاز:** `{cpu_limit}%`\n"
        f"💾 **حداکثر RAM مجاز:** `{ram_limit}%`\n"
        f"💿 **حداکثر DISK مجاز:** `{disk_limit}%`"
    )

    # استفاده از ماژول کیبورد
    reply_markup = keyboard.resource_limits_kb(cpu_limit, ram_limit, disk_limit)

    await safe_edit_message(update, txt, reply_markup=reply_markup)


async def toggle_down_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.set_setting(update.effective_user.id, 'down_alert_enabled', update.callback_query.data.split('_')[2])
    await schedules_settings_menu(update, context)


async def ask_cpu_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_edit_message(update, "🧠 **حداکثر درصد مجاز CPU (0-100):**", reply_markup=keyboard.get_cancel_markup())
    return GET_CPU_LIMIT


async def save_cpu_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = int(update.message.text)
        if 1 <= val <= 100:
            db.set_setting(update.effective_user.id, 'cpu_threshold', val)
            await update.message.reply_text(f"✅ ذخیره شد: {val}%")
            await resource_settings_menu(update, context)
            return ConversationHandler.END
    except:
        pass
    await update.message.reply_text("❌ عدد نامعتبر.")
    return GET_CPU_LIMIT


async def ask_ram_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_edit_message(update, "💾 **حداکثر درصد مجاز RAM (0-100):**", reply_markup=keyboard.get_cancel_markup())
    return GET_RAM_LIMIT


async def save_ram_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = int(update.message.text)
        if 1 <= val <= 100:
            db.set_setting(update.effective_user.id, 'ram_threshold', val)
            await update.message.reply_text(f"✅ ذخیره شد: {val}%")
            await resource_settings_menu(update, context)
            return ConversationHandler.END
    except:
        pass
    await update.message.reply_text("❌ عدد نامعتبر.")
    return GET_RAM_LIMIT


async def ask_disk_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_edit_message(update, "💿 **حداکثر درصد مجاز Disk (0-100):**", reply_markup=keyboard.get_cancel_markup())
    return GET_DISK_LIMIT


async def save_disk_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = int(update.message.text)
        if 1 <= val <= 100:
            db.set_setting(update.effective_user.id, 'disk_threshold', val)
            await update.message.reply_text(f"✅ ذخیره شد: {val}%")
            await resource_settings_menu(update, context)
            return ConversationHandler.END
    except:
        pass
    await update.message.reply_text("❌ عدد نامعتبر.")
    return GET_DISK_LIMIT


async def ask_custom_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_edit_message(update, "✍️ **بازه زمانی (دقیقه) را وارد کنید:**", reply_markup=keyboard.get_cancel_markup())
    return GET_CUSTOM_INTERVAL


async def set_custom_interval_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        minutes = int(update.message.text)
        if 10 <= minutes <= 1440:
            db.set_setting(update.effective_user.id, 'report_interval', minutes * 60)
            await update.message.reply_text(f"✅ تنظیم شد: هر {minutes} دقیقه.")
            await settings_cron_menu(update, context)
            return ConversationHandler.END
    except:
        pass
    await update.message.reply_text("❌ عدد نامعتبر (بین 10 تا 1440).")
    return GET_CUSTOM_INTERVAL


async def add_channel_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_edit_message(
        update,
        "📝 **افزودن کانال جدید**\n\n"
        "لطفاً **آیدی عددی کانال** را ارسال کنید.\n"
        "مثال: `-100123456789`\n\n"
        "⚠️ **نکته:** ابتدا ربات را در کانال **ادمین** کنید.",
        reply_markup=keyboard.get_cancel_markup()
    )
    return GET_CHANNEL_FORWARD


async def get_channel_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        msg = update.message
        text = getattr(msg, 'text', '').strip()

        # اعتبارسنجی: آیدی باید با -100 شروع شود یا @ داشته باشد
        if not text or (not text.startswith('-100') and not text.startswith('@')):
            await msg.reply_text(
                "❌ **فرمت نامعتبر!**\n\n"
                "لطفاً فقط **آیدی عددی** (شروع با -100) یا **یوزرنیم** (شروع با @) بفرستید.\n"
                "مثال صحیح: `-100123456789`"
            )
            return GET_CHANNEL_FORWARD

        c_id = text
        c_name = "Channel (Manual)"

        # تلاش برای گرفتن اسم کانال جهت اطمینان
        try:
            chat = await context.bot.get_chat(c_id)
            c_name = chat.title
            c_id = str(chat.id)  # تبدیل نهایی به آیدی عددی
        except Exception as e:
            # اگر ربات ادمین نباشد یا آیدی غلط باشد
            await msg.reply_text(
                f"❌ **ربات نتوانست کانال را پیدا کند!**\n\n"
                f"1️⃣ مطمئن شوید آیدی `{text}` صحیح است.\n"
                f"2️⃣ مطمئن شوید ربات در کانال **ادمین** است.\n"
                f"خطا: {e}"
            )
            return GET_CHANNEL_FORWARD

        context.user_data['new_chan'] = {'id': c_id, 'name': c_name}

        kb = [
            [InlineKeyboardButton("🔥 فقط فشار منابع (CPU/RAM)", callback_data='type_resource')],
            [InlineKeyboardButton("🚨 فقط هشدار قطعی", callback_data='type_down'), InlineKeyboardButton("⏳ فقط انقضا", callback_data='type_expiry')],
            [InlineKeyboardButton("📊 فقط گزارشات", callback_data='type_report'), InlineKeyboardButton("✅ همه موارد", callback_data='type_all')]
        ]

        await msg.reply_text(
            f"✅ کانال **{c_name}** شناسایی شد.\n🆔 آیدی: `{c_id}`\n\n🛠 **این کانال برای دریافت چه نوع پیام‌هایی استفاده شود؟**",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return GET_CHANNEL_TYPE

    except Exception as e:
        logger.error(f"Channel Add Error: {e}")
        await msg.reply_text("❌ خطای غیرمنتظره. دوباره تلاش کنید.")
        return GET_CHANNEL_FORWARD


async def set_channel_type_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except:
        pass
    usage = query.data.split('_')[1]
    cdata = context.user_data['new_chan']
    db.add_channel(update.effective_user.id, cdata['id'], cdata['name'], usage)
    await query.message.reply_text(f"✅ کانال {cdata['name']} ثبت شد.")
    await channels_menu(update, context)
    return ConversationHandler.END


async def delete_channel_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.delete_channel(int(update.callback_query.data.split('_')[1]), update.effective_user.id)
    await channels_menu(update, context)


async def edit_expiry_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except:
        pass
    sid = query.data.split('_')[2]
    context.user_data['edit_expiry_sid'] = sid
    srv = db.get_server_by_id(sid)
    txt = (
        f"📅 **تغییر زمان انقضای سرور: {srv['name']}**\n\n"
        f"🔢 لطفاً **تعداد روزهای باقی‌مانده** را به عدد وارد کنید.\n"
        f"مثلاً اگر عدد `30` را بفرستید، انقضا روی ۳۰ روز دیگر تنظیم می‌شود.\n\n"
        f"♾ برای **نامحدود** کردن، عدد `0` را بفرستید."
    )
    await safe_edit_message(update, txt, reply_markup=keyboard.get_cancel_markup())
    return EDIT_SERVER_EXPIRY


async def edit_expiry_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        days = int(update.message.text)
        sid = context.user_data.get('edit_expiry_sid')
        if days > 0:
            new_date = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')
            msg = f"✅ تاریخ انقضا با موفقیت روی **{days} روز دیگر** تنظیم شد."
        else:
            new_date = None
            msg = "✅ سرور با موفقیت **نامحدود (Lifetime)** شد."
        db.update_server_expiry(sid, new_date)
        await update.message.reply_text(msg)
        await server_detail(update, context, custom_sid=sid)
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ لطفاً فقط عدد انگلیسی وارد کنید.")
        return EDIT_SERVER_EXPIRY


async def ask_terminal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except:
        pass

    sid = query.data.split('_')[2]
    srv = db.get_server_by_id(sid)
    context.user_data['term_sid'] = sid

    kb = [[InlineKeyboardButton("🔙 خروج و بازگشت به پنل", callback_data='exit_terminal')]]

    txt = (
        f"📟 **ترمینال تعاملی: {srv['name']}**\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"🟢 **اتصال برقرار شد.**\n"
        f"هر دستوری بنویسی اجرا میشه. برای خروج دکمه پایین رو بزن.\n\n"
        f"root@{srv['ip']}:~# _"
    )

    await query.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return GET_REMOTE_COMMAND


async def run_terminal_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cmd = update.message.text
    if cmd.lower() in ['exit', 'quit']:
        return await close_terminal_session(update, context)

    sid = context.user_data.get('term_sid')
    srv = db.get_server_by_id(sid)

    wait_msg = await update.message.reply_text(f"⚙️ `{cmd}` ...")

    real_pass = sec.decrypt(srv['password'])
    ok, output = await asyncio.get_running_loop().run_in_executor(None, ServerMonitor.run_remote_command, srv['ip'], srv['port'], srv['username'], real_pass, cmd)

    if not output: output = "[No Output]"
    if len(output) > 3000: output = output[:3000] + "\n..."
    safe_output = html.escape(output)
    status = "✅" if ok else "❌"

    terminal_view = (
        f"<code>root@{srv['ip']}:~# {cmd}</code>\n"
        f"{status}\n"
        f"<pre language='bash'>{safe_output}</pre>"
    )

    kb = [[InlineKeyboardButton("🔙 خروج از ترمینال", callback_data='exit_terminal')]]
    await wait_msg.delete()
    try:
        await update.message.reply_text(terminal_view, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(kb))
    except:
        await update.message.reply_text(f"⚠️ Raw Output:\n{output}", reply_markup=InlineKeyboardMarkup(kb))

    return GET_REMOTE_COMMAND


async def close_terminal_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        try:
            await update.callback_query.answer()
        except:
            pass
    sid = context.user_data.get('term_sid')
    await server_detail(update, context, custom_sid=sid)
    return ConversationHandler.END
# ==============================================================================
# 🌍 GLOBAL OPERATIONS (NEW FEATURES)
# ==============================================================================

async def global_ops_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش منوی عملیات همگانی"""
    # استفاده از ماژول کیبورد
    reply_markup = keyboard.global_ops_kb()

    txt = (
        "🌍 **تنظیمات همگانی سرورها**\n\n"
        "در این بخش می‌تونی یک دستور رو همزمان روی **تمام سرورهای فعال** اجرا کنی.\n"
        "⚠️ نکته: عملیات ممکن است بسته به تعداد سرورها کمی طول بکشد."
    )
    await safe_edit_message(update, txt, reply_markup=reply_markup)


async def global_action_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت درخواست‌های همگانی"""
    query = update.callback_query
    action = query.data.split('_')[2]  # update, ram, disk, full
    uid = update.effective_user.id
    servers = db.get_all_user_servers(uid)
    active_servers = [s for s in servers if s['is_active']]

    if not active_servers:
        await query.answer("❌ هیچ سرور فعالی نداری!", show_alert=True)
        return

    await query.message.reply_text(
        f"⏳ **عملیات در حال اجرا روی {len(active_servers)} سرور...**\n"
        "لطفاً منتظر بمانید، نتیجه نهایی ارسال خواهد شد."
    )

    asyncio.create_task(cronjobs.run_global_commands_background(context, uid, active_servers, action))


# ==============================================================================
# ⏱ AUTO SCHEDULE HANDLERS (CRONJOBS)
# ==============================================================================

async def auto_update_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """منوی تنظیم زمان‌بندی آپدیت خودکار"""
    if update.callback_query:
        await update.callback_query.answer()

    uid = update.effective_user.id
    curr = db.get_setting(uid, 'auto_update_hours') or '0'

    # استفاده از ماژول کیبورد
    reply_markup = keyboard.auto_update_kb(curr)

    txt = (
        "🔄 **تنظیم آپدیت خودکار مخازن (APT Update)**\n"
        "➖➖➖➖➖➖➖➖➖➖\n"
        "ربات می‌تواند به صورت دوره‌ای دستور `apt-get update && upgrade` را روی تمام سرورهای فعال اجرا کند.\n\n"
        "👇 بازه زمانی مورد نظر را انتخاب کنید:"
    )

    await safe_edit_message(update, txt, reply_markup=reply_markup)


async def auto_reboot_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """منوی اصلی وضعیت ریبوت خودکار"""
    if update.callback_query:
        await update.callback_query.answer()

    uid = update.effective_user.id
    curr_setting = db.get_setting(uid, 'auto_reboot_config')

    status_txt = "❌ غیرفعال"
    if curr_setting and curr_setting != 'OFF':
        try:
            days, time_str = curr_setting.split('|')
            days = int(days)
            freq_map = {1: "هر روز", 2: "هر ۲ روز", 7: "هفتگی", 14: "هر ۲ هفته", 30: "ماهانه"}
            freq_txt = freq_map.get(days, f"هر {days} روز")
            status_txt = f"✅ {freq_txt} - ساعت {time_str}"
        except:
            status_txt = "⚠️ نامعتبر"

    txt = (
        "⚠️ **تنظیم ریبوت خودکار سرورها**\n"
        "➖➖➖➖➖➖➖➖➖➖\n"
        "🔴 **هشدار:** ریبوت شدن سرور باعث قطع موقت اتصال کاربران می‌شود.\n"
        "در این بخش می‌توانید تعیین کنید تمام سرورها سر ساعت مشخصی ریبوت شوند.\n\n"
        f"وضعیت فعلی: `{status_txt}`"
    )

    # استفاده از ماژول کیبورد
    reply_markup = keyboard.auto_reboot_kb()

    await safe_edit_message(update, txt, reply_markup=reply_markup)


async def ask_reboot_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پرسیدن ساعت از کاربر"""
    try:
        await update.callback_query.answer()
    except:
        pass

    txt = (
        "🕰 **تنظیم ساعت ریبوت**\n\n"
        "لطفاً ساعتی که می‌خواهید ریبوت انجام شود را به صورت عدد وارد کنید.\n"
        "🔢 بازه مجاز: `0` تا `23`\n\n"
        "مثال: برای ۴ صبح عدد `4` و برای ۲ بعدازظهر عدد `14` را ارسال کنید."
    )
    await safe_edit_message(update, txt, reply_markup=keyboard.get_cancel_markup())
    return GET_REBOOT_TIME


async def receive_reboot_time_and_show_freq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت ساعت و نمایش دکمه‌های فرکانس"""
    try:
        hour = int(update.message.text)
        if not (0 <= hour <= 23):
            raise ValueError()

        time_str = f"{hour:02d}:00"
        context.user_data['temp_reboot_time'] = time_str

        txt = (
            f"✅ ساعت انتخاب شده: `{time_str}`\n\n"
            "📅 **حالا بازه زمانی تکرار را انتخاب کنید:**"
        )

        # استفاده از ماژول کیبورد
        reply_markup = keyboard.reboot_freq_kb(time_str)

        await update.message.reply_text(txt, reply_markup=reply_markup, parse_mode='Markdown')
        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text("❌ عدد نامعتبر! لطفاً عددی بین 0 تا 23 وارد کنید.")
        return GET_REBOOT_TIME


async def save_auto_reboot_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ذخیره نهایی تنظیمات ریبوت"""
    query = update.callback_query
    data = query.data
    uid = update.effective_user.id

    if data == 'disable_reboot':
        db.set_setting(uid, 'auto_reboot_config', 'OFF')
        await query.answer("✅ ریبوت خودکار غیرفعال شد.", show_alert=True)
        await auto_reboot_menu(update, context)
        return

    parts = data.split('_')
    days = parts[1]
    time_str = parts[2]

    config_str = f"{days}|{time_str}"
    db.set_setting(uid, 'auto_reboot_config', config_str)
    db.set_setting(uid, 'last_reboot_date', '2000-01-01')

    await query.answer(f"✅ تنظیم شد: هر {days} روز ساعت {time_str}")
    await auto_reboot_menu(update, context)
# --- تابع اجرایی جاب (Job) ---


async def save_auto_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ذخیره تنظیمات آپدیت خودکار"""
    query = update.callback_query
    uid = update.effective_user.id
    hours = query.data.split('_')[2]

    db.set_setting(uid, 'auto_update_hours', hours)

    if hours == '0':
        msg = "❌ آپدیت خودکار غیرفعال شد."
    else:
        msg = f"✅ آپدیت خودکار تنظیم شد: هر {hours} ساعت."

    try:
        await query.answer(msg, show_alert=True)
    except:
        pass

    await auto_update_menu(update, context)
async def show_payment_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش اطلاعات پرداخت (داینامیک از دیتابیس)"""
    query = update.callback_query
    method_type = query.data.split('_')[2]  # card or tron (که ما در دیتابیس card/crypto داریم)

    # مپ کردن دکمه‌های قدیمی به تایپ‌های دیتابیس
    db_type = 'card' if method_type == 'card' else 'crypto'

    plan_key = context.user_data.get('selected_plan')
    if not plan_key:
        await wallet_menu(update, context)
        return

    plan = SUBSCRIPTION_PLANS[plan_key]
    user_id = update.effective_user.id

    # دریافت روش‌های فعال از دیتابیس
    methods = db.get_payment_methods(db_type)

    if not methods:
        await safe_edit_message(update, "❌ متاسفانه در حال حاضر هیچ روش پرداختی برای این گزینه فعال نیست.\nلطفاً با پشتیبانی تماس بگیرید.")
        return

    # ثبت سفارش اولیه
    pay_id = db.create_payment(user_id, plan_key, plan['price'], method_type)

    details_txt = ""
    if db_type == 'card':
        details_txt = f"💳 **شماره کارت‌های فعال:**\n\n"
        for m in methods:
            details_txt += (
                f"🏦 **{m['network']}**\n"
                f"👤 {m['holder_name']}\n"
                f"🔢 `{m['address']}`\n"
                f"──────────────\n"
            )
        amount_txt = f"💰 مبلغ قابل پرداخت: `{plan['price']:,} تومان`"

    else:  # Crypto
        details_txt = f"💎 **آدرس‌های واریز (Crypto):**\n\n"
        for m in methods:
            details_txt += (
                f"🪙 **شبکه: {m['network']}**\n"
                f"🔗 آدرس:\n`{m['address']}`\n"
                f"(روی آدرس بزنید کپی می‌شود)\n"
                f"──────────────\n"
            )
        # اینجا مبلغ تومانی است. اگر بخواهید تتری باشد باید نرخ تبدیل داشته باشید
        # فعلاً همان تومانی را نمایش می‌دهیم
        amount_txt = f"💰 مبلغ معادل تومن: `{plan['price']:,} تومان`\n⚠️ لطفاً معادل تتری/ارزی را محاسبه و واریز کنید."

    txt = (
        f"{details_txt}"
        f"{amount_txt}\n\n"
        f"📝 **دستورالعمل:**\n"
        f"۱. مبلغ را به یکی از روش‌های بالا واریز کنید.\n"
        f"۲. اسکرین‌شات تراکنش را آماده کنید.\n"
        f"۳. دکمه **'✅ پرداخت کردم'** را بزنید."
    )

    # استفاده از ماژول کیبورد
    reply_markup = keyboard.confirm_payment_kb(pay_id)
    
    await safe_edit_message(update, txt, reply_markup=reply_markup)


async def ask_for_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مرحله ۱: درخواست ارسال رسید از کاربر"""
    query = update.callback_query
    # فرمت دیتا: confirm_pay_ID
    pay_id = query.data.split('_')[2]

    # ذخیره آیدی پرداخت در حافظه موقت برای مرحله بعد
    context.user_data['current_pay_id'] = pay_id

    txt = (
        "📸 **لطفاً تصویر رسید پرداخت را ارسال کنید.**\n\n"
        "می‌توانید عکس بگیرید یا فایل (Screenshot) بفرستید.\n"
        "برای انصراف دکمه زیر را بزنید."
    )

    await safe_edit_message(update, txt, reply_markup=keyboard.get_cancel_markup())
    return GET_RECEIPT


async def process_receipt_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مرحله ۲: دریافت عکس، ذخیره و ارسال برای ادمین"""
    pay_id = context.user_data.get('current_pay_id')
    if not pay_id:
        await update.message.reply_text("❌ خطای نشست. لطفاً دوباره تلاش کنید.")
        return ConversationHandler.END

    user = update.effective_user

    # پیدا کردن اطلاعات پرداخت از دیتابیس
    with db.get_connection() as (conn, cur):
        cur.execute("SELECT * FROM payments WHERE id=%s", (pay_id,))
        pay_info = cur.fetchone()

    if not pay_info:
        await update.message.reply_text("❌ تراکنش یافت نشد.")
        return ConversationHandler.END

    # تشخیص نوع فایل ارسالی (عکس فشرده یا فایل)
    if update.message.photo:
        # همیشه باکیفیت‌ترین عکس (آخرین در لیست) را برمی‌داریم
        file_id = update.message.photo[-1].file_id
        is_document = False
    elif update.message.document:
        file_id = update.message.document.file_id
        is_document = True
    else:
        await update.message.reply_text("❌ لطفاً فقط **عکس** یا **فایل تصویری** ارسال کنید.")
        return GET_RECEIPT

    # پیام تشکر به کاربر
    await update.message.reply_text(
        "✅ **رسید شما دریافت شد!**\n\n"
        "مدیران سیستم پس از بررسی صحت پرداخت، اشتراک شما را فعال خواهند کرد.\n"
        "این فرآیند معمولاً کمتر از ۱ ساعت زمان می‌برد.",
        reply_markup=keyboard.back_btn()
    )

    # --- ارسال به ادمین ---
    plan = SUBSCRIPTION_PLANS.get(pay_info['plan_type'])
    plan_name = plan['name'] if plan else "Unknown"

    admin_caption = (
        f"💰 **درخواست پرداخت جدید (همراه با رسید)**\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"👤 کاربر: {user.full_name} (`{user.id}`)\n"
        f"📦 سرویس: {plan_name}\n"
        f"💵 مبلغ: {pay_info['amount']:,}\n"
        f"💳 روش: {pay_info['method']}\n"
        f"🔢 شناسه پرداخت: `{pay_id}`\n\n"
        f"⚠️ لطفاً رسید را چک کنید و تصمیم بگیرید."
    )

    # استفاده از ماژول کیبورد
    admin_kb = keyboard.admin_receipt_kb(pay_id)

    try:
        if is_document:
            await context.bot.send_document(chat_id=SUPER_ADMIN_ID, document=file_id, caption=admin_caption, reply_markup=admin_kb, parse_mode='Markdown')
        else:
            await context.bot.send_photo(chat_id=SUPER_ADMIN_ID, photo=file_id, caption=admin_caption, reply_markup=admin_kb, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Failed to send receipt to admin: {e}")
        # اگر ارسال عکس شکست خورد، متنی بفرست
        await context.bot.send_message(chat_id=SUPER_ADMIN_ID, text=admin_caption + "\n\n❌ (عکس رسید ارسال نشد، خطا در تلگرام)", reply_markup=admin_kb)

    return ConversationHandler.END


async def admin_approve_payment_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تایید نهایی توسط ادمین"""
    query = update.callback_query
    pay_id = query.data.split('_')[3]

    res = db.approve_payment(pay_id)

    if res:
        user_id, plan_name = res
        await safe_edit_message(update, f"✅ پرداخت #{pay_id} تایید شد.\nسرویس {plan_name} برای کاربر فعال گردید.")
        try:
            await context.bot.send_message(chat_id=user_id, text=f"🎉 **تبریک! پرداخت شما تایید شد.**\n\n✅ اشتراک **{plan_name}** فعال شد.")
        except:
            pass
    else:
        await safe_edit_message(update, "❌ خطا: این پرداخت قبلاً تایید شده است.")


async def admin_reject_payment_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pay_id = update.callback_query.data.split('_')[3]
    await safe_edit_message(update, f"❌ پرداخت #{pay_id} رد شد.")
async def referral_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """منوی سیستم دعوت پیشرفته"""
    if update.callback_query:
        await update.callback_query.answer()

    uid = update.effective_user.id
    user = db.get_user(uid)
    bot_username = context.bot.username

    invite_link = f"https://t.me/{bot_username}?start={uid}"
    ref_count = user['referral_count'] if user['referral_count'] else 0

    txt = (
        f"💎 **کمپین بزرگ دعوت دوستان**\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"دوستات رو دعوت کن، سرور رایگان بگیر! 🎁\n\n"
        f"🔰 **قوانین و پاداش‌ها:**\n"
        f"به ازای هر نفری که با لینک شما عضو شود:\n\n"
        f"1️⃣ **+10 روز** به اعتبار کل اکانتت اضافه میشه ⏳\n"
        f"2️⃣ **+1 عدد** ظرفیت سرور هدیه می‌گیری 🖥\n"
        f"   ╰ *(نکته: ظرفیت هدیه ۱۰ روزه است و بعد از آن منقضی می‌شود)*\n\n"
        f"📊 **عملکرد شما:**\n"
        f"👥 تعداد زیرمجموعه: `{ref_count} نفر`\n"
        f"📅 اعتبار فعلی شما: `{user['expiry_date']}`\n\n"
        f"🔗 **لینک اختصاصی شما (لمس کنید):**\n"
        f"`{invite_link}`"
    )

    # استفاده از ماژول کیبورد
    reply_markup = keyboard.referral_kb(invite_link)
    
    await safe_edit_message(update, txt, reply_markup=reply_markup)


# ==============================================================================
# 📊 DASHBOARD SORTING FEATURES
# ==============================================================================
async def dashboard_sort_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش منوی انتخاب نوع مرتب‌سازی"""
    query = update.callback_query
    try:
        await query.answer()
    except:
        pass

    # حالت فعلی رو می‌خونیم
    current_sort = context.user_data.get('dash_sort', 'id')

    txt = (
        "📊 **تنظیمات نمایش داشبورد**\n"
        "➖➖➖➖➖➖➖➖➖➖\n"
        "می‌خواهید لیست سرورها بر چه اساسی مرتب شود؟"
    )

    # استفاده از ماژول کیبورد
    reply_markup = keyboard.dashboard_sort_kb(current_sort)

    await safe_edit_message(update, txt, reply_markup=reply_markup)


async def set_dashboard_sort_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ذخیره انتخاب کاربر و بازگشت به داشبورد"""
    query = update.callback_query
    sort_type = query.data.split('_')[3]  # uptime, traffic, etc.

    context.user_data['dash_sort'] = sort_type

    # ترجمه فارسی برای پیام تایید
    names = {'uptime': 'آپتایم', 'traffic': 'ترافیک', 'resource': 'منابع', 'id': 'زمان ثبت'}
    await query.answer(f"✅ مرتب‌سازی بر اساس {names.get(sort_type)} تنظیم شد.")

    # مستقیم برمی‌گردیم به داشبورد با تنظیمات جدید
    await status_dashboard(update, context)
# ==============================================================================
# 🎯 ADMIN REPORTS (ADVANCED)
# ==============================================================================

# State for User ID Input
ADMIN_GET_UID_FOR_REPORT = range(300)
async def admin_server_detail_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش حرفه‌ای جزئیات سرور (استفاده مجدد از server_detail)"""
    sid = update.callback_query.data.split('_')[2]
    # از تابع موجود server_detail استفاده می‌شود
    await server_detail(update, context, custom_sid=sid)
# ==============================================================================
# 📡 TUNNEL MONITORING ADMIN FLOW (REWRITTEN & ADVANCED)
# ==============================================================================

async def monitor_settings_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پنل مدیریت سرور مانیتورینگ (هوشمند)"""
    uid = update.effective_user.id
    if uid != SUPER_ADMIN_ID: return
    
    if update.callback_query:
        try: await update.callback_query.answer()
        except: pass

    # بررسی اینکه آیا سرور مانیتورینگ وجود دارد یا خیر
    with db.get_connection() as (conn, cur):
        cur.execute("SELECT * FROM servers WHERE is_monitor_node=1")
        monitor = cur.fetchone()

    # استفاده از ماژول کیبورد
    is_set = monitor is not None
    reply_markup = keyboard.monitor_node_kb(is_set)

    if not monitor:
        # --- حالت اول: هنوز سرور ست نشده ---
        desc = (
            "📡 **سیستم مانیتورینگ تانل (Iran Node)**\n"
            "➖➖➖➖➖➖➖➖➖➖\n"
            "در این سیستم، یک سرور ایران وظیفه تست مداوم کانفیگ‌های شما را بر عهده می‌گیرد.\n\n"
            "⚠️ **وضعیت فعلی:** هنوز سرور ایران ست نشده است.\n\n"
            "✅ با کلیک بر روی دکمه زیر، مراحل نصب خودکار آغاز می‌شود:"
        )
    else:
        # --- حالت دوم: سرور فعال است ---
        ip_censored = monitor['ip'] # نمایش آی‌پی
        desc = (
            "📡 **سیستم مانیتورینگ تانل (Iran Node)**\n"
            "➖➖➖➖➖➖➖➖➖➖\n"
            f"✅ **وضعیت:** فعال و متصل\n"
            f"🖥 **نام سرور:** `{monitor['name']}`\n"
            f"🌐 **آی‌پی:** `{ip_censored}`\n\n"
            "📂 **مدیریت فایل‌ها و ارتباط:**"
        )

    await safe_edit_message(update, desc, reply_markup=reply_markup)


# --- استیت‌های دریافت مشخصات سرور ایران ---
async def set_iran_monitor_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_edit_message(update, "📝 **یک نام برای سرور ایران انتخاب کنید:**\n(مثلاً: Iran-MCI)", reply_markup=keyboard.get_cancel_markup())
    return GET_IRAN_NAME

async def get_iran_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['iran_name'] = update.message.text
    await update.message.reply_text("🇮🇷 **آی‌پی سرور ایران را وارد کنید:**", reply_markup=keyboard.get_cancel_markup())
    return GET_IRAN_IP

async def get_iran_ip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['iran_ip'] = update.message.text
    await update.message.reply_text("🔌 **پورت اتصال SSH را وارد کنید (پیش‌فرض 22):**", reply_markup=keyboard.get_cancel_markup())
    return GET_IRAN_PORT

async def get_iran_port(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        port = int(update.message.text)
        context.user_data['iran_port'] = port
        await update.message.reply_text("👤 **نام کاربری (Username) سرور ایران:**\n(معمولاً root)", reply_markup=keyboard.get_cancel_markup())
        return GET_IRAN_USER
    except:
        await update.message.reply_text("❌ لطفاً عدد وارد کنید.")
        return GET_IRAN_PORT

async def get_iran_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['iran_user'] = update.message.text
    await update.message.reply_text("🔑 **رمز عبور (Password) سرور ایران:**", reply_markup=keyboard.get_cancel_markup())
    return GET_IRAN_PASS

async def get_iran_pass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text
    
    # اطلاعات جمع آوری شده
    name = context.user_data.get('iran_name')
    ip = context.user_data.get('iran_ip')
    port = context.user_data.get('iran_port')
    user = context.user_data.get('iran_user')

    if not name or not ip:
        await update.message.reply_text("⚠️ اطلاعات ناقص است. مجدد تلاش کنید.")
        return ConversationHandler.END

    # پیام اولیه (شروع عملیات)
    progress_msg = await update.message.reply_text(
        "🚀 **آغاز عملیات نصب و راه‌اندازی...**\n"
        "⏳ در حال برقراری ارتباط با سرور ایران..."
    )

    loop = asyncio.get_running_loop()

    # --- تابع داخلی برای اجرای مراحل نصب ---
    def install_process_sync():
        log_steps = []
        client = None
        try:
            # 1. اتصال
            client = ServerMonitor.get_ssh_client(ip, port, user, password)
            log_steps.append("✅ اتصال SSH برقرار شد.")
            
            # 2. آماده‌سازی محیط لاگ
            # ساخت فایل لاگ و دادن دسترسی کامل برای ثبت ریزترین خطاها
            log_setup_cmd = "touch /root/agent_debug.log && chmod 777 /root/agent_debug.log && echo '--- LOG STARTED ---' > /root/agent_debug.log"
            client.exec_command(log_setup_cmd)
            log_steps.append("📝 فایل لاگ دیباگ ساخته شد.")

            # 3. آپلود فایل ایجنت
            sftp = client.open_sftp()
            try:
                sftp.mkdir("/root/xray_workspace")
            except: pass # اگر پوشه بود خطا نده
            
            with sftp.file("/root/monitor_agent.py", "w") as remote_file:
                remote_file.write(get_agent_content())
            sftp.close()
            log_steps.append("📂 فایل مانیتورینگ منتقل شد.")

            # 4. نصب پیش‌نیازها و Xray (این مرحله زمان‌بر است)
            log_steps.append("📦 در حال نصب پکیج‌ها (Python, Curl, Unzip)...")
            
            # دستور نصب (بدون پرسش)
            setup_cmd = (
                "export DEBIAN_FRONTEND=noninteractive; "
                "apt-get update -y > /dev/null 2>&1 && "
                "apt-get install -y python3 python3-requests curl unzip > /dev/null 2>&1 && " # 👈 python3-requests اضافه شد
                "chmod +x /root/monitor_agent.py"
            )
            
            # اجرا با timeout بالا چون آپدیت مخازن ایران کند است
            stdin, stdout, stderr = client.exec_command(setup_cmd, timeout=300)
            exit_status = stdout.channel.recv_exit_status()
            
            if exit_status != 0:
                err = stderr.read().decode()
                raise Exception(f"خطا در نصب پکیج‌ها: {err}")
            
            log_steps.append("✅ نصب پکیج‌ها با موفقیت انجام شد.")
            client.close()
            return True, log_steps

        except Exception as e:
            if client: client.close()
            return False, str(e)

    # --- اجرای مرحله به مرحله در ترد جداگانه (چون SSH بلاک‌کننده است) ---
    # اما چون می‌خواهیم پیام آپدیت شود، کمی تریک می‌زنیم یا کل فانکشن را یکجا اجرا می‌کنیم
    # برای سادگی و جلوگیری از هنگ کردن بات، کل پروسه را در executor می‌بریم
    # و فقط نتیجه نهایی را چک می‌کنیم (یا می‌توانیم لاجیک پیچیده‌تر برای استریم داشته باشیم)
    # اینجا برای تجربه کاربری بهتر، پیام را چند بار فیک آپدیت می‌کنیم تا حس انجام کار بدهد
    
    # تسک واقعی در پس‌زمینه
    task = loop.run_in_executor(None, install_process_sync)
    
    # حلقه نمایش وضعیت فیک (چون دسترسی به لاگ لحظه‌ای ترد سخت است)
    steps_visual = [
        "📂 در حال انتقال فایل‌های سیستمی...",
        "📝 در حال تنظیم سیستم لاگ‌برداری دقیق...",
        "📦 در حال نصب Xray Core و وابستگی‌ها...",
        "☕️ لطفاً صبر کنید (سرورهای ایران کند هستند)...",
        "⚙️ در حال پیکربندی نهایی..."
    ]
    
    for step in steps_visual:
        if task.done(): break
        try:
            await progress_msg.edit_text(f"🚀 **نصب خودکار روی سرور ایران**\n\n{step}\n⏳ لطفاً صبر کنید...")
        except: pass
        await asyncio.sleep(4) # هر ۴ ثانیه پیام عوض شود

    # انتظار برای پایان واقعی کار
    success, result = await task
    
    if success:
        # ثبت در دیتابیس
        real_name = f"🇮🇷 {name}"
        encrypted_pass = sec.encrypt(password)
        
        try:
            with db.get_connection() as (conn, cur):
                # غیرفعال کردن مانیتورهای قبلی
                cur.execute("UPDATE servers SET is_monitor_node = 0")
                
                # حذف اگر قبلاً با این نام بوده
                cur.execute("DELETE FROM servers WHERE owner_id = %s AND name = %s", (SUPER_ADMIN_ID, real_name))
                
                # ایجاد جدید
                cur.execute('''
                    INSERT INTO servers (owner_id, name, ip, port, username, password, is_monitor_node, is_active, location_type, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, 1, 1, 'ir', NOW())
                ''', (SUPER_ADMIN_ID, real_name, ip, port, user, encrypted_pass))
                conn.commit()

            await progress_msg.edit_text(
                f"✅ **عملیات با موفقیت تکمیل شد!**\n\n"
                f"🔹 فایل مانیتورینگ نصب شد.\n"
                f"🔹 فایل لاگ `agent_debug.log` ساخته شد.\n"
                f"🔹 سرور به عنوان نود مانیتورینگ فعال گردید.\n\n"
                f"از این پس تست کانفیگ‌ها از طریق این سرور انجام می‌شود."
            )
            # بازگشت به پنل مانیتورینگ برای دیدن گزینه‌های جدید
            await asyncio.sleep(3)
            await monitor_settings_panel(update, context)

        except Exception as e:
            await progress_msg.edit_text(f"❌ خطا در ذخیره دیتابیس:\n{e}")
    else:
        # نمایش خطا
        await progress_msg.edit_text(f"❌ **عملیات شکست خورد!**\n\nخطا: `{result}`")

    return ConversationHandler.END


async def delete_monitor_node(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف فایل‌ها از سرور ایران و قطع ارتباط"""
    query = update.callback_query
    await query.answer("🗑 در حال حذف فایل‌ها و قطع ارتباط...", show_alert=True)
    msg = await query.message.reply_text("⏳ **در حال پاکسازی سرور ایران...**")

    with db.get_connection() as (conn, cur):
        cur.execute("SELECT * FROM servers WHERE is_monitor_node=1")
        monitor = cur.fetchone()

    if not monitor:
        await msg.edit_text("❌ سروری یافت نشد.")
        return

    # دستورات پاکسازی
    cleanup_cmd = "rm -rf /root/monitor_agent.py /root/agent_debug.log /root/xray_workspace"
    
    loop = asyncio.get_running_loop()
    try:
        # تلاش برای وصل شدن و پاک کردن فایل‌ها
        await loop.run_in_executor(
            None, ServerMonitor.run_remote_command, 
            monitor['ip'], monitor['port'], monitor['username'], sec.decrypt(monitor['password']),
            cleanup_cmd, 20
        )
        server_cleaned = True
    except:
        server_cleaned = False # شاید سرور خاموشه، ولی از دیتابیس پاک میکنیم

    # حذف از دیتابیس (یا فقط برداشتن فلگ مانیتور)
    db.delete_server(monitor['id'], SUPER_ADMIN_ID)

    text = "✅ **ارتباط قطع شد.**\n"
    text += "🔹 سرور از لیست ربات حذف شد.\n"
    if server_cleaned:
        text += "🔹 فایل‌های مانیتورینگ و لاگ‌ها از سرور ایران پاک شدند."
    else:
        text += "⚠️ نکته: نتوانستیم به سرور وصل شویم تا فایل‌ها را پاک کنیم (احتمالاً سرور خاموش است)."

    await msg.edit_text(text)
    await asyncio.sleep(2)
    await monitor_settings_panel(update, context)
async def update_monitor_node(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بررسی بروزرسانی و ریپلیس کردن فایل‌ها"""
    query = update.callback_query
    await query.answer("🔄 در حال بررسی و آپدیت فایل‌ها...", show_alert=True)
    msg = await query.message.reply_text("⏳ **در حال بروزرسانی فایل‌های سرور ایران...**")

    with db.get_connection() as (conn, cur):
        cur.execute("SELECT * FROM servers WHERE is_monitor_node=1")
        monitor = cur.fetchone()

    if not monitor:
        await msg.edit_text("❌ سرور مانیتورینگ یافت نشد.")
        return

    ip, port, user = monitor['ip'], monitor['port'], monitor['username']
    password = sec.decrypt(monitor['password'])

    loop = asyncio.get_running_loop()

    def update_process():
        try:
            client = ServerMonitor.get_ssh_client(ip, port, user, password)
            sftp = client.open_sftp()
            
            # آپلود مجدد فایل ایجنت (جایگزینی)
            with sftp.file("/root/monitor_agent.py", "w") as remote_file:
                remote_file.write(get_agent_content())
            sftp.close()
            
            # اطمینان از وجود فایل لاگ و دسترسی‌ها
            cmds = (
                "chmod +x /root/monitor_agent.py && "
                "touch /root/agent_debug.log && "
                "chmod 777 /root/agent_debug.log && "
                "echo '--- UPDATED AT $(date) ---' >> /root/agent_debug.log"
            )
            client.exec_command(cmds)
            client.close()
            return True, "Success"
        except Exception as e:
            return False, str(e)

    success, result = await loop.run_in_executor(None, update_process)

    if success:
        await msg.edit_text(
            "✅ **بروزرسانی موفقیت‌آمیز بود.**\n\n"
            "🔹 فایل `monitor_agent.py` جایگزین شد.\n"
            "🔹 دسترسی فایل لاگ بررسی شد.\n"
            "🔹 سیستم آماده کار است."
        )
    else:
        await msg.edit_text(f"❌ **خطا در بروزرسانی:**\n`{result}`")

# ==============================================================================
# 🎮 UI HELPERS & GENERAL HANDLERS
# ==============================================================================
# get_cancel_markup حذف شد چون در ماژول کیبورد وجود دارد

async def safe_edit_message(update: Update, text, reply_markup=None, parse_mode='Markdown'):
    try:
        if update.callback_query:
            # اگر متن و کیبورد تغییر نکرده باشد، تلگرام ارور میدهد. اینجا هندل میکنیم
            await update.callback_query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
        elif update.message:
            await update.message.reply_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
    except BadRequest as e:
        # اگر ارور این بود که "پیام تغییر نکرده"، نادیده بگیر
        if "Message is not modified" in str(e):
            return
        logger.error(f"Edit Error: {e}")
    except Exception as e:
        logger.error(f"General Edit Error: {e}")


async def cancel_handler_func(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        try:
            await update.callback_query.answer()
        except:
            pass
    await safe_edit_message(update, "🚫 **عملیات لغو شد.**")
    await asyncio.sleep(1)
    await start(update, context)
    return ConversationHandler.END


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ارسال لاگ خطا به ادمین در تلگرام"""
    logger.error("Exception while handling an update:", exc_info=context.error)
    
    # ساخت متن کامل خطا
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)
    
    # پیام خطا برای ارسال به ادمین
    message = (
        f"🚨 **CRITICAL ERROR** 🚨\n\n"
        f"Update: <pre>{html.escape(str(update))}</pre>\n\n"
        f"❌ Error:\n<pre>{html.escape(tb_string[-3500:])}</pre>"
    )
    
    # چاپ در کنسول برای اطمینان
    print(tb_string)

    # ارسال به تلگرام ادمین
    try:
        if SUPER_ADMIN_ID:
            await context.bot.send_message(chat_id=SUPER_ADMIN_ID, text=message, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Failed to send error log to admin: {e}")
async def run_background_ssh_task(context: ContextTypes.DEFAULT_TYPE, chat_id, func, *args):
    loop = asyncio.get_running_loop()
    try:
        ok, output = await loop.run_in_executor(None, func, *args)
        clean_out = html.escape(str(output))
        if len(clean_out) > 3500:
            clean_out = clean_out[:3500] + "\n... (Output Truncated)"

        status_icon = "✅ عملیات با موفقیت انجام شد." if ok else "❌ عملیات با خطا مواجه شد."
        msg_text = (
            f"{status_icon}\n"
            f"➖➖➖➖➖➖➖➖➖➖\n"
            f"<pre>{clean_out}</pre>"
        )
        await context.bot.send_message(chat_id=chat_id, text=msg_text, parse_mode='HTML')

    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"⚠️ خطای غیرمنتظره در عملیات پس‌زمینه:\n{e}")

async def show_payment_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش اطلاعات پرداخت (داینامیک از دیتابیس)"""
    query = update.callback_query
    method_type = query.data.split('_')[2]  # card or tron (که ما در دیتابیس card/crypto داریم)

    # مپ کردن دکمه‌های قدیمی به تایپ‌های دیتابیس
    db_type = 'card' if method_type == 'card' else 'crypto'

    plan_key = context.user_data.get('selected_plan')
    if not plan_key:
        await wallet_menu(update, context)
        return

    plan = SUBSCRIPTION_PLANS[plan_key]
    user_id = update.effective_user.id

    # دریافت روش‌های فعال از دیتابیس
    methods = db.get_payment_methods(db_type)

    if not methods:
        await safe_edit_message(update, "❌ متاسفانه در حال حاضر هیچ روش پرداختی برای این گزینه فعال نیست.\nلطفاً با پشتیبانی تماس بگیرید.")
        return

    # ثبت سفارش اولیه
    pay_id = db.create_payment(user_id, plan_key, plan['price'], method_type)

    details_txt = ""
    if db_type == 'card':
        details_txt = f"💳 **شماره کارت‌های فعال:**\n\n"
        for m in methods:
            details_txt += (
                f"🏦 **{m['network']}**\n"
                f"👤 {m['holder_name']}\n"
                f"🔢 `{m['address']}`\n"
                f"──────────────\n"
            )
        amount_txt = f"💰 مبلغ قابل پرداخت: `{plan['price']:,} تومان`"

    else:  # Crypto
        details_txt = f"💎 **آدرس‌های واریز (Crypto):**\n\n"
        for m in methods:
            details_txt += (
                f"🪙 **شبکه: {m['network']}**\n"
                f"🔗 آدرس:\n`{m['address']}`\n"
                f"(روی آدرس بزنید کپی می‌شود)\n"
                f"──────────────\n"
            )
        # اینجا مبلغ تومانی است. اگر بخواهید تتری باشد باید نرخ تبدیل داشته باشید
        # فعلاً همان تومانی را نمایش می‌دهیم
        amount_txt = f"💰 مبلغ معادل تومن: `{plan['price']:,} تومان`\n⚠️ لطفاً معادل تتری/ارزی را محاسبه و واریز کنید."

    txt = (
        f"{details_txt}"
        f"{amount_txt}\n\n"
        f"📝 **دستورالعمل:**\n"
        f"۱. مبلغ را به یکی از روش‌های بالا واریز کنید.\n"
        f"۲. اسکرین‌شات تراکنش را آماده کنید.\n"
        f"۳. دکمه **'✅ پرداخت کردم'** را بزنید."
    )

    # استفاده از ماژول کیبورد
    reply_markup = keyboard.confirm_payment_kb(pay_id)
    
    await safe_edit_message(update, txt, reply_markup=reply_markup)


async def ask_for_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مرحله ۱: درخواست ارسال رسید از کاربر"""
    query = update.callback_query
    # فرمت دیتا: confirm_pay_ID
    pay_id = query.data.split('_')[2]

    # ذخیره آیدی پرداخت در حافظه موقت برای مرحله بعد
    context.user_data['current_pay_id'] = pay_id

    txt = (
        "📸 **لطفاً تصویر رسید پرداخت را ارسال کنید.**\n\n"
        "می‌توانید عکس بگیرید یا فایل (Screenshot) بفرستید.\n"
        "برای انصراف دکمه زیر را بزنید."
    )

    await safe_edit_message(update, txt, reply_markup=keyboard.get_cancel_markup())
    return GET_RECEIPT


async def process_receipt_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مرحله ۲: دریافت عکس، ذخیره و ارسال برای ادمین"""
    pay_id = context.user_data.get('current_pay_id')
    if not pay_id:
        await update.message.reply_text("❌ خطای نشست. لطفاً دوباره تلاش کنید.")
        return ConversationHandler.END

    user = update.effective_user

    # پیدا کردن اطلاعات پرداخت از دیتابیس
    with db.get_connection() as (conn, cur):
        pay_info = cur.execute("SELECT * FROM payments WHERE id=?", (pay_id,)).fetchone()

    if not pay_info:
        await update.message.reply_text("❌ تراکنش یافت نشد.")
        return ConversationHandler.END

    # تشخیص نوع فایل ارسالی (عکس فشرده یا فایل)
    if update.message.photo:
        # همیشه باکیفیت‌ترین عکس (آخرین در لیست) را برمی‌داریم
        file_id = update.message.photo[-1].file_id
        is_document = False
    elif update.message.document:
        file_id = update.message.document.file_id
        is_document = True
    else:
        await update.message.reply_text("❌ لطفاً فقط **عکس** یا **فایل تصویری** ارسال کنید.")
        return GET_RECEIPT

    # پیام تشکر به کاربر
    await update.message.reply_text(
        "✅ **رسید شما دریافت شد!**\n\n"
        "مدیران سیستم پس از بررسی صحت پرداخت، اشتراک شما را فعال خواهند کرد.\n"
        "این فرآیند معمولاً کمتر از ۱ ساعت زمان می‌برد.",
        reply_markup=keyboard.back_btn()
    )

    # --- ارسال به ادمین ---
    plan = SUBSCRIPTION_PLANS.get(pay_info['plan_type'])
    plan_name = plan['name'] if plan else "Unknown"

    admin_caption = (
        f"💰 **درخواست پرداخت جدید (همراه با رسید)**\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"👤 کاربر: {user.full_name} (`{user.id}`)\n"
        f"📦 سرویس: {plan_name}\n"
        f"💵 مبلغ: {pay_info['amount']:,}\n"
        f"💳 روش: {pay_info['method']}\n"
        f"🔢 شناسه پرداخت: `{pay_id}`\n\n"
        f"⚠️ لطفاً رسید را چک کنید و تصمیم بگیرید."
    )

    # استفاده از ماژول کیبورد
    admin_kb = keyboard.admin_receipt_kb(pay_id)

    try:
        if is_document:
            await context.bot.send_document(chat_id=SUPER_ADMIN_ID, document=file_id, caption=admin_caption, reply_markup=admin_kb, parse_mode='Markdown')
        else:
            await context.bot.send_photo(chat_id=SUPER_ADMIN_ID, photo=file_id, caption=admin_caption, reply_markup=admin_kb, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Failed to send receipt to admin: {e}")
        # اگر ارسال عکس شکست خورد، متنی بفرست
        await context.bot.send_message(chat_id=SUPER_ADMIN_ID, text=admin_caption + "\n\n❌ (عکس رسید ارسال نشد، خطا در تلگرام)", reply_markup=admin_kb)

    return ConversationHandler.END


async def admin_approve_payment_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تایید نهایی توسط ادمین"""
    query = update.callback_query
    pay_id = query.data.split('_')[3]

    res = db.approve_payment(pay_id)

    if res:
        user_id, plan_name = res
        await safe_edit_message(update, f"✅ پرداخت #{pay_id} تایید شد.\nسرویس {plan_name} برای کاربر فعال گردید.")
        try:
            await context.bot.send_message(chat_id=user_id, text=f"🎉 **تبریک! پرداخت شما تایید شد.**\n\n✅ اشتراک **{plan_name}** فعال شد.")
        except:
            pass
    else:
        await safe_edit_message(update, "❌ خطا: این پرداخت قبلاً تایید شده است.")


async def admin_reject_payment_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pay_id = update.callback_query.data.split('_')[3]
    await safe_edit_message(update, f"❌ پرداخت #{pay_id} رد شد.")
async def referral_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """منوی سیستم دعوت پیشرفته"""
    if update.callback_query:
        await update.callback_query.answer()

    uid = update.effective_user.id
    user = db.get_user(uid)
    bot_username = context.bot.username

    invite_link = f"https://t.me/{bot_username}?start={uid}"
    ref_count = user['referral_count'] if user['referral_count'] else 0

    txt = (
        f"💎 **کمپین بزرگ دعوت دوستان**\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"دوستات رو دعوت کن، سرور رایگان بگیر! 🎁\n\n"
        f"🔰 **قوانین و پاداش‌ها:**\n"
        f"به ازای هر نفری که با لینک شما عضو شود:\n\n"
        f"1️⃣ **+10 روز** به اعتبار کل اکانتت اضافه میشه ⏳\n"
        f"2️⃣ **+1 عدد** ظرفیت سرور هدیه می‌گیری 🖥\n"
        f"   ╰ *(نکته: ظرفیت هدیه ۱۰ روزه است و بعد از آن منقضی می‌شود)*\n\n"
        f"📊 **عملکرد شما:**\n"
        f"👥 تعداد زیرمجموعه: `{ref_count} نفر`\n"
        f"📅 اعتبار فعلی شما: `{user['expiry_date']}`\n\n"
        f"🔗 **لینک اختصاصی شما (لمس کنید):**\n"
        f"`{invite_link}`"
    )

    # استفاده از ماژول کیبورد
    reply_markup = keyboard.referral_kb(invite_link)
    
    await safe_edit_message(update, txt, reply_markup=reply_markup)


# ==============================================================================
# 📊 DASHBOARD SORTING FEATURES
# ==============================================================================
async def dashboard_sort_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش منوی انتخاب نوع مرتب‌سازی"""
    query = update.callback_query
    try:
        await query.answer()
    except:
        pass

    # حالت فعلی رو می‌خونیم
    current_sort = context.user_data.get('dash_sort', 'id')

    txt = (
        "📊 **تنظیمات نمایش داشبورد**\n"
        "➖➖➖➖➖➖➖➖➖➖\n"
        "می‌خواهید لیست سرورها بر چه اساسی مرتب شود؟"
    )

    # استفاده از ماژول کیبورد
    reply_markup = keyboard.dashboard_sort_kb(current_sort)

    await safe_edit_message(update, txt, reply_markup=reply_markup)


async def set_dashboard_sort_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ذخیره انتخاب کاربر و بازگشت به داشبورد"""
    query = update.callback_query
    sort_type = query.data.split('_')[3]  # uptime, traffic, etc.

    context.user_data['dash_sort'] = sort_type

    # ترجمه فارسی برای پیام تایید
    names = {'uptime': 'آپتایم', 'traffic': 'ترافیک', 'resource': 'منابع', 'id': 'زمان ثبت'}
    await query.answer(f"✅ مرتب‌سازی بر اساس {names.get(sort_type)} تنظیم شد.")

    # مستقیم برمی‌گردیم به داشبورد با تنظیمات جدید
    await status_dashboard(update, context)
# ==============================================================================
# 🎯 ADMIN REPORTS (ADVANCED)
# ==============================================================================

# State for User ID Input
ADMIN_GET_UID_FOR_REPORT = range(300)
async def admin_server_detail_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش حرفه‌ای جزئیات سرور (استفاده مجدد از server_detail)"""
    sid = update.callback_query.data.split('_')[2]
    # از تابع موجود server_detail استفاده می‌شود
    await server_detail(update, context, custom_sid=sid)
# ==============================================================================
# 📡 TUNNEL MONITORING ADMIN FLOW (REWRITTEN & ADVANCED)
# ==============================================================================

async def monitor_settings_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پنل مدیریت سرور مانیتورینگ (هوشمند)"""
    uid = update.effective_user.id
    if uid != SUPER_ADMIN_ID: return
    
    if update.callback_query:
        try: await update.callback_query.answer()
        except: pass

    # بررسی اینکه آیا سرور مانیتورینگ وجود دارد یا خیر
    with db.get_connection() as (conn, cur):
        monitor = cur.execute("SELECT * FROM servers WHERE is_monitor_node=1").fetchone()

    # استفاده از ماژول کیبورد
    is_set = monitor is not None
    reply_markup = keyboard.monitor_node_kb(is_set)

    if not monitor:
        # --- حالت اول: هنوز سرور ست نشده ---
        desc = (
            "📡 **سیستم مانیتورینگ تانل (Iran Node)**\n"
            "➖➖➖➖➖➖➖➖➖➖\n"
            "در این سیستم، یک سرور ایران وظیفه تست مداوم کانفیگ‌های شما را بر عهده می‌گیرد.\n\n"
            "⚠️ **وضعیت فعلی:** هنوز سرور ایران ست نشده است.\n\n"
            "✅ با کلیک بر روی دکمه زیر، مراحل نصب خودکار آغاز می‌شود:"
        )
    else:
        # --- حالت دوم: سرور فعال است ---
        ip_censored = monitor['ip'] # نمایش آی‌پی
        desc = (
            "📡 **سیستم مانیتورینگ تانل (Iran Node)**\n"
            "➖➖➖➖➖➖➖➖➖➖\n"
            f"✅ **وضعیت:** فعال و متصل\n"
            f"🖥 **نام سرور:** `{monitor['name']}`\n"
            f"🌐 **آی‌پی:** `{ip_censored}`\n\n"
            "📂 **مدیریت فایل‌ها و ارتباط:**"
        )

    await safe_edit_message(update, desc, reply_markup=reply_markup)


# --- استیت‌های دریافت مشخصات سرور ایران ---
async def set_iran_monitor_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_edit_message(update, "📝 **یک نام برای سرور ایران انتخاب کنید:**\n(مثلاً: Iran-MCI)", reply_markup=keyboard.get_cancel_markup())
    return GET_IRAN_NAME

async def get_iran_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['iran_name'] = update.message.text
    await update.message.reply_text("🇮🇷 **آی‌پی سرور ایران را وارد کنید:**", reply_markup=keyboard.get_cancel_markup())
    return GET_IRAN_IP

async def get_iran_ip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['iran_ip'] = update.message.text
    await update.message.reply_text("🔌 **پورت اتصال SSH را وارد کنید (پیش‌فرض 22):**", reply_markup=keyboard.get_cancel_markup())
    return GET_IRAN_PORT

async def get_iran_port(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        port = int(update.message.text)
        context.user_data['iran_port'] = port
        await update.message.reply_text("👤 **نام کاربری (Username) سرور ایران:**\n(معمولاً root)", reply_markup=keyboard.get_cancel_markup())
        return GET_IRAN_USER
    except:
        await update.message.reply_text("❌ لطفاً عدد وارد کنید.")
        return GET_IRAN_PORT

async def get_iran_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['iran_user'] = update.message.text
    await update.message.reply_text("🔑 **رمز عبور (Password) سرور ایران:**", reply_markup=keyboard.get_cancel_markup())
    return GET_IRAN_PASS

async def get_iran_pass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text
    
    # اطلاعات جمع آوری شده
    name = context.user_data.get('iran_name')
    ip = context.user_data.get('iran_ip')
    port = context.user_data.get('iran_port')
    user = context.user_data.get('iran_user')

    if not name or not ip:
        await update.message.reply_text("⚠️ اطلاعات ناقص است. مجدد تلاش کنید.")
        return ConversationHandler.END

    # پیام اولیه (شروع عملیات)
    progress_msg = await update.message.reply_text(
        "🚀 **آغاز عملیات نصب و راه‌اندازی...**\n"
        "⏳ در حال برقراری ارتباط با سرور ایران..."
    )

    loop = asyncio.get_running_loop()

    # --- تابع داخلی برای اجرای مراحل نصب ---
    def install_process_sync():
        log_steps = []
        client = None
        try:
            # 1. اتصال
            client = ServerMonitor.get_ssh_client(ip, port, user, password)
            log_steps.append("✅ اتصال SSH برقرار شد.")
            
            # 2. آماده‌سازی محیط لاگ
            # ساخت فایل لاگ و دادن دسترسی کامل برای ثبت ریزترین خطاها
            log_setup_cmd = "touch /root/agent_debug.log && chmod 777 /root/agent_debug.log && echo '--- LOG STARTED ---' > /root/agent_debug.log"
            client.exec_command(log_setup_cmd)
            log_steps.append("📝 فایل لاگ دیباگ ساخته شد.")

            # 3. آپلود فایل ایجنت
            sftp = client.open_sftp()
            try:
                sftp.mkdir("/root/xray_workspace")
            except: pass # اگر پوشه بود خطا نده
            
            with sftp.file("/root/monitor_agent.py", "w") as remote_file:
                remote_file.write(get_agent_content())
            sftp.close()
            log_steps.append("📂 فایل مانیتورینگ منتقل شد.")

            # 4. نصب پیش‌نیازها و Xray (این مرحله زمان‌بر است)
            log_steps.append("📦 در حال نصب پکیج‌ها (Python, Curl, Unzip)...")
            
            # دستور نصب (بدون پرسش)
            setup_cmd = (
                "export DEBIAN_FRONTEND=noninteractive; "
                "apt-get update -y > /dev/null 2>&1 && "
                "apt-get install -y python3 python3-requests curl unzip > /dev/null 2>&1 && " # 👈 python3-requests اضافه شد
                "chmod +x /root/monitor_agent.py"
            )
            
            # اجرا با timeout بالا چون آپدیت مخازن ایران کند است
            stdin, stdout, stderr = client.exec_command(setup_cmd, timeout=300)
            exit_status = stdout.channel.recv_exit_status()
            
            if exit_status != 0:
                err = stderr.read().decode()
                raise Exception(f"خطا در نصب پکیج‌ها: {err}")
            
            log_steps.append("✅ نصب پکیج‌ها با موفقیت انجام شد.")
            client.close()
            return True, log_steps

        except Exception as e:
            if client: client.close()
            return False, str(e)

    # --- اجرای مرحله به مرحله در ترد جداگانه (چون SSH بلاک‌کننده است) ---
    # اما چون می‌خواهیم پیام آپدیت شود، کمی تریک می‌زنیم یا کل فانکشن را یکجا اجرا می‌کنیم
    # برای سادگی و جلوگیری از هنگ کردن بات، کل پروسه را در executor می‌بریم
    # و فقط نتیجه نهایی را چک می‌کنیم (یا می‌توانیم لاجیک پیچیده‌تر برای استریم داشته باشیم)
    # اینجا برای تجربه کاربری بهتر، پیام را چند بار فیک آپدیت می‌کنیم تا حس انجام کار بدهد
    
    # تسک واقعی در پس‌زمینه
    task = loop.run_in_executor(None, install_process_sync)
    
    # حلقه نمایش وضعیت فیک (چون دسترسی به لاگ لحظه‌ای ترد سخت است)
    steps_visual = [
        "📂 در حال انتقال فایل‌های سیستمی...",
        "📝 در حال تنظیم سیستم لاگ‌برداری دقیق...",
        "📦 در حال نصب Xray Core و وابستگی‌ها...",
        "☕️ لطفاً صبر کنید (سرورهای ایران کند هستند)...",
        "⚙️ در حال پیکربندی نهایی..."
    ]
    
    for step in steps_visual:
        if task.done(): break
        try:
            await progress_msg.edit_text(f"🚀 **نصب خودکار روی سرور ایران**\n\n{step}\n⏳ لطفاً صبر کنید...")
        except: pass
        await asyncio.sleep(4) # هر ۴ ثانیه پیام عوض شود

    # انتظار برای پایان واقعی کار
    success, result = await task
    
    if success:
        # ثبت در دیتابیس
        real_name = f"🇮🇷 {name}"
        encrypted_pass = sec.encrypt(password)
        
        try:
            with db.get_connection() as (conn, cur):
                # غیرفعال کردن مانیتورهای قبلی
                cur.execute("UPDATE servers SET is_monitor_node = 0")
                
                # حذف اگر قبلاً با این نام بوده
                cur.execute("DELETE FROM servers WHERE owner_id = ? AND name = ?", (SUPER_ADMIN_ID, real_name))
                
                # ایجاد جدید
                cur.execute('''
                    INSERT INTO servers (owner_id, name, ip, port, username, password, is_monitor_node, is_active, location_type, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, 1, 1, 'ir', datetime('now'))
                ''', (SUPER_ADMIN_ID, real_name, ip, port, user, encrypted_pass))
                conn.commit()

            await progress_msg.edit_text(
                f"✅ **عملیات با موفقیت تکمیل شد!**\n\n"
                f"🔹 فایل مانیتورینگ نصب شد.\n"
                f"🔹 فایل لاگ `agent_debug.log` ساخته شد.\n"
                f"🔹 سرور به عنوان نود مانیتورینگ فعال گردید.\n\n"
                f"از این پس تست کانفیگ‌ها از طریق این سرور انجام می‌شود."
            )
            # بازگشت به پنل مانیتورینگ برای دیدن گزینه‌های جدید
            await asyncio.sleep(3)
            await monitor_settings_panel(update, context)

        except Exception as e:
            await progress_msg.edit_text(f"❌ خطا در ذخیره دیتابیس:\n{e}")
    else:
        # نمایش خطا
        await progress_msg.edit_text(f"❌ **عملیات شکست خورد!**\n\nخطا: `{result}`")

    return ConversationHandler.END


async def delete_monitor_node(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف فایل‌ها از سرور ایران و قطع ارتباط"""
    query = update.callback_query
    await query.answer("🗑 در حال حذف فایل‌ها و قطع ارتباط...", show_alert=True)
    msg = await query.message.reply_text("⏳ **در حال پاکسازی سرور ایران...**")

    with db.get_connection() as (conn, cur):
        monitor = cur.execute("SELECT * FROM servers WHERE is_monitor_node=1").fetchone()

    if not monitor:
        await msg.edit_text("❌ سروری یافت نشد.")
        return

    # دستورات پاکسازی
    cleanup_cmd = "rm -rf /root/monitor_agent.py /root/agent_debug.log /root/xray_workspace"
    
    loop = asyncio.get_running_loop()
    try:
        # تلاش برای وصل شدن و پاک کردن فایل‌ها
        await loop.run_in_executor(
            None, ServerMonitor.run_remote_command, 
            monitor['ip'], monitor['port'], monitor['username'], sec.decrypt(monitor['password']),
            cleanup_cmd, 20
        )
        server_cleaned = True
    except:
        server_cleaned = False # شاید سرور خاموشه، ولی از دیتابیس پاک میکنیم

    # حذف از دیتابیس (یا فقط برداشتن فلگ مانیتور)
    db.delete_server(monitor['id'], SUPER_ADMIN_ID)

    text = "✅ **ارتباط قطع شد.**\n"
    text += "🔹 سرور از لیست ربات حذف شد.\n"
    if server_cleaned:
        text += "🔹 فایل‌های مانیتورینگ و لاگ‌ها از سرور ایران پاک شدند."
    else:
        text += "⚠️ نکته: نتوانستیم به سرور وصل شویم تا فایل‌ها را پاک کنیم (احتمالاً سرور خاموش است)."

    await msg.edit_text(text)
    await asyncio.sleep(2)
    await monitor_settings_panel(update, context)
async def update_monitor_node(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بررسی بروزرسانی و ریپلیس کردن فایل‌ها"""
    query = update.callback_query
    await query.answer("🔄 در حال بررسی و آپدیت فایل‌ها...", show_alert=True)
    msg = await query.message.reply_text("⏳ **در حال بروزرسانی فایل‌های سرور ایران...**")

    with db.get_connection() as (conn, cur):
        monitor = cur.execute("SELECT * FROM servers WHERE is_monitor_node=1").fetchone()

    if not monitor:
        await msg.edit_text("❌ سرور مانیتورینگ یافت نشد.")
        return

    ip, port, user = monitor['ip'], monitor['port'], monitor['username']
    password = sec.decrypt(monitor['password'])

    loop = asyncio.get_running_loop()

    def update_process():
        try:
            client = ServerMonitor.get_ssh_client(ip, port, user, password)
            sftp = client.open_sftp()
            
            # آپلود مجدد فایل ایجنت (جایگزینی)
            with sftp.file("/root/monitor_agent.py", "w") as remote_file:
                remote_file.write(get_agent_content())
            sftp.close()
            
            # اطمینان از وجود فایل لاگ و دسترسی‌ها
            cmds = (
                "chmod +x /root/monitor_agent.py && "
                "touch /root/agent_debug.log && "
                "chmod 777 /root/agent_debug.log && "
                "echo '--- UPDATED AT $(date) ---' >> /root/agent_debug.log"
            )
            client.exec_command(cmds)
            client.close()
            return True, "Success"
        except Exception as e:
            return False, str(e)

    success, result = await loop.run_in_executor(None, update_process)

    if success:
        await msg.edit_text(
            "✅ **بروزرسانی موفقیت‌آمیز بود.**\n\n"
            "🔹 فایل `monitor_agent.py` جایگزین شد.\n"
            "🔹 دسترسی فایل لاگ بررسی شد.\n"
            "🔹 سیستم آماده کار است."
        )
    else:
        await msg.edit_text(f"❌ **خطا در بروزرسانی:**\n`{result}`")

# ==============================================================================
# 🎮 UI HELPERS & GENERAL HANDLERS
# ==============================================================================
# get_cancel_markup حذف شد چون در ماژول کیبورد وجود دارد

async def safe_edit_message(update: Update, text, reply_markup=None, parse_mode='Markdown'):
    try:
        if update.callback_query:
            # اگر متن و کیبورد تغییر نکرده باشد، تلگرام ارور میدهد. اینجا هندل میکنیم
            await update.callback_query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
        elif update.message:
            await update.message.reply_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
    except BadRequest as e:
        # اگر ارور این بود که "پیام تغییر نکرده"، نادیده بگیر
        if "Message is not modified" in str(e):
            return
        logger.error(f"Edit Error: {e}")
    except Exception as e:
        logger.error(f"General Edit Error: {e}")


async def cancel_handler_func(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        try:
            await update.callback_query.answer()
        except:
            pass
    await safe_edit_message(update, "🚫 **عملیات لغو شد.**")
    await asyncio.sleep(1)
    await start(update, context)
    return ConversationHandler.END


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ارسال لاگ خطا به ادمین در تلگرام"""
    logger.error("Exception while handling an update:", exc_info=context.error)
    
    # ساخت متن کامل خطا
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)
    
    # پیام خطا برای ارسال به ادمین
    message = (
        f"🚨 **CRITICAL ERROR** 🚨\n\n"
        f"Update: <pre>{html.escape(str(update))}</pre>\n\n"
        f"❌ Error:\n<pre>{html.escape(tb_string[-3500:])}</pre>"
    )
    
    # چاپ در کنسول برای اطمینان
    print(tb_string)

    # ارسال به تلگرام ادمین
    try:
        if SUPER_ADMIN_ID:
            await context.bot.send_message(chat_id=SUPER_ADMIN_ID, text=message, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Failed to send error log to admin: {e}")
async def run_background_ssh_task(context: ContextTypes.DEFAULT_TYPE, chat_id, func, *args):
    loop = asyncio.get_running_loop()
    try:
        ok, output = await loop.run_in_executor(None, func, *args)
        clean_out = html.escape(str(output))
        if len(clean_out) > 3500:
            clean_out = clean_out[:3500] + "\n... (Output Truncated)"

        status_icon = "✅ عملیات با موفقیت انجام شد." if ok else "❌ عملیات با خطا مواجه شد."
        msg_text = (
            f"{status_icon}\n"
            f"➖➖➖➖➖➖➖➖➖➖\n"
            f"<pre>{clean_out}</pre>"
        )
        await context.bot.send_message(chat_id=chat_id, text=msg_text, parse_mode='HTML')

    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"⚠️ خطای غیرمنتظره در عملیات پس‌زمینه:\n{e}")

# ==============================================================================
# 📝 CONFIG MANAGEMENT (NEW GRAPHICAL MENU)
# ==============================================================================

async def add_config_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع پروسه افزودن کانفیگ - دریافت لینک"""
    if update.callback_query:
        await update.callback_query.answer()
        
    txt = (
        "📥 **افزودن کانفیگ جدید**\n\n"
        "لطفاً لینک خود را ارسال کنید (پشتیبانی از تمام پروتکل‌ها).\n"
        "ما خودمان نوع آن را تشخیص می‌دهیم یا از شما می‌پرسیم.\n\n"
        "👇 لینک (vmess/vless/http...) را ارسال کنید:"
    )
    
    await safe_edit_message(update, txt, reply_markup=keyboard.get_cancel_markup())
    return GET_CONFIG_LINKS

# --- هندلرهای انتخاب مود ---
async def mode_ask_json(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    txt = (
        "📄 **لطفاً کانفیگ JSON خود را ارسال کنید.**\n\n"
        "می‌توانید:\n"
        "1️⃣ متن JSON را همینجا پیست کنید.\n"
        "2️⃣ فایل `.json` را آپلود کنید.\n\n"
        "⚠️ ساختار باید استاندارد Xray Outbound باشد."
    )
    await safe_edit_message(update, txt, reply_markup=keyboard.get_cancel_markup())
    return GET_JSON_CONF


async def mode_ask_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    txt = (
        "🔗 **لطفاً لینک سابسکریپشن را ارسال کنید.**\n\n"
        "فرمت مثال:\n"
        "`https://example.com/sub/xyz...`"
    )
    await safe_edit_message(update, txt, reply_markup=keyboard.get_cancel_markup())
    return GET_SUB_LINK


# --- پردازش فایل/متن JSON ---
async def process_json_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    config_content = ""

    # 1. دریافت محتوا (متن یا فایل)
    if update.message.document:
        f = await update.message.document.get_file()
        byte_arr = await f.download_as_bytearray()
        config_content = byte_arr.decode('utf-8')
    elif update.message.text:
        config_content = update.message.text
    else:
        await update.message.reply_text("❌ لطفاً فقط متن یا فایل ارسال کنید.")
        return GET_JSON_CONF

    # 2. اعتبارسنجی JSON
    try:
        data = json.loads(config_content)
        # اگر جیسون معتبر بود، اسمش را از تگ برمی‌داریم
        name = data.get('tag', f"JSON_{int(time.time())}")

        # ذخیره در دیتابیس (کانفیگ را مینیفای می‌کنیم تا در یک خط جا شود)
        minified_json = json.dumps(data)
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        with db.get_connection() as (conn, cur):
            cur.execute(
                "INSERT INTO tunnel_configs (owner_id, type, link, name, added_at) VALUES (?, 'json', ?, ?, ?)",
                (uid, minified_json, name, now)
            )
            conn.commit()

        await update.message.reply_text(f"✅ **کانفیگ JSON با موفقیت ثبت شد.**\n🏷 نام: `{name}`")
        await asyncio.sleep(1)
        await start(update, context)
        return ConversationHandler.END

    except json.JSONDecodeError:
        await update.message.reply_text("❌ **فرمت JSON نامعتبر است!**\nلطفاً کدهای ارسالی را چک کنید.")
        return GET_JSON_CONF
    except Exception as e:
        await update.message.reply_text(f"❌ خطای ناشناخته: {e}")
        return ConversationHandler.END

async def process_sub_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    uid = update.effective_user.id

    if not link.startswith(('http://', 'https://')):
        await update.message.reply_text("❌ لینک باید با http یا https شروع شود.")
        return GET_SUB_LINK

    msg = await update.message.reply_text("⏳ **در حال دریافت و آنالیز کانفیگ‌ها...**")

    # دریافت اطلاعات سرور ایران
    with db.get_connection() as (conn, cur):
        monitor = cur.execute("SELECT * FROM servers WHERE is_monitor_node=1").fetchone()

    if not monitor:
        await msg.edit_text("❌ سرور مانیتورینگ فعال نیست.")
        return ConversationHandler.END

    ip, port, user = monitor['ip'], monitor['port'], monitor['username']
    password = sec.decrypt(monitor['password'])
    cmd = f"python3 /root/monitor_agent.py {shlex.quote(link)}"

    loop = asyncio.get_running_loop()
    # افزایش تایم‌اوت به 30 ثانیه برای ساب‌های سنگین
    ok, output = await loop.run_in_executor(None, ServerMonitor.run_remote_command, ip, port, user, password, cmd, 30)

    try:
        data = None
        for line in output.split('\n'):
            line = line.strip()
            if not line: continue
            try:
                temp = json.loads(line)
                if temp.get('type') == 'sub':
                    data = temp
                    break
            except:
                pass
        if not data:
            data = extract_safe_json(output)

        if not data:
             raise Exception("Invalid Agent Output (No JSON found)")
        
        if data.get('type') == 'sub':
            configs = data.get('configs', [])
            count = len(configs)

            if count == 0:
                await msg.edit_text("❌ کانفیگی یافت نشد.")
                return ConversationHandler.END
            
            # نام‌گذاری ساب
            sub_name = f"Sub_{int(time.time())}"
            if "remarks" in link:
                 try: sub_name = urllib.parse.parse_qs(urllib.parse.urlparse(link).query).get('remarks', [sub_name])[0]
                 except: pass

            await msg.edit_text(f"✅ **{count} کانفیگ شناسایی شد.**\n⬇️ در حال ثبت در دیتابیس...")
            
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            with db.get_connection() as (conn, cur):
                for i, cfg in enumerate(configs):
                    # دریافت نام و لینک از دیکشنری جدید
                    real_name = cfg.get('name', 'Unknown')
                    conf_link = cfg.get('link')
                    
                    # اگر نام نداشت، یک نام پیش‌فرض بساز
                    if real_name == "Unknown" or not real_name:
                        real_name = f"{sub_name}_{i + 1}"
                    
                    # تمیزکاری نام
                    real_name = urllib.parse.unquote(real_name).replace('+', ' ').strip()

                    cur.execute(
                        "INSERT INTO tunnel_configs (owner_id, type, link, name, added_at, quality_score) VALUES (?, 'sub_item', ?, ?, ?, 10)",
                        (uid, conf_link, real_name, now)
                    )
                conn.commit()

            await msg.edit_text(
                f"✅ **عملیات موفق!**\n"
                f"📂 نام مجموعه: `{sub_name}`\n"
                f"🔢 تعداد ثبت شده: `{count}` کانفیگ"
            )
            await asyncio.sleep(2)
            await start(update, context)
            return ConversationHandler.END

    except Exception as e:
        await msg.edit_text(f"❌ خطا در پردازش: {e}")
        return ConversationHandler.END

# ==============================================================================
# 🚇 TUNNEL CONFIG MANAGER (ADVANCED)
# ==============================================================================
async def tunnel_list_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """منوی انتخاب نوع لیست کانفیگ (نسخه اصلاح شده و ضد کرش)"""
    logger.info("🟢 Entering tunnel_list_menu function...") # لاگ ورود
    
    try:
        # --- بخش اصلاح شده برای جلوگیری از کرش ---
        if update.callback_query:
            try:
                await update.callback_query.answer()
                logger.debug("Callback answered successfully.")
            except Exception as e:
                # اگر دکمه منقضی شده بود، فقط در لاگ بنویس و رد شو (کرش نکن)
                logger.warning(f"Callback answer ignored (Timeout/Old Query): {e}")
        # -------------------------------------------
        
        txt = (
            "📑 **مدیریت کانفیگ‌ها**\n\n"
            "لطفاً نوع نمایش را انتخاب کنید:"
        )
        
        logger.debug("Generating Keyboard from keyboard.py...")
        # ساخت کیبورد
        reply_markup = keyboard.tunnel_list_mode_kb()
        logger.debug(f"Keyboard Generated: {reply_markup}")

        logger.debug("Sending message to user...")
        await safe_edit_message(update, txt, reply_markup=reply_markup)
        logger.info("✅ tunnel_list_menu finished successfully.")

    except Exception as e:
        # اگر خطای دیگری رخ داد، لاگ بگیر و به کاربر بگو
        logger.error(f"❌ CRITICAL ERROR in tunnel_list_menu: {e}")
        logger.error(traceback.format_exc()) # چاپ ریز مکالمات خطا
        
        if update.callback_query:
            try:
                await update.callback_query.message.reply_text("❌ خطایی در نمایش منو رخ داد. لطفاً دوباره تلاش کنید.")
            except: pass

    except Exception as e:
        # اگر هر خطایی رخ بده اینجا چاپ میشه
        logger.error(f"❌ ERROR in tunnel_list_menu: {e}")
        logger.error(traceback.format_exc()) # چاپ ریز مکالمات خطا
        
        # یه پیام هم به کاربر نشون میدیم که بفهمه خراب شده
        if update.callback_query:
            await update.callback_query.message.reply_text(f"❌ خطا در بخش مدیریت کانفیگ:\n{e}")
async def perform_fast_scan(context, uid, mode):
    """تست سریع کانفیگ‌ها قبل از نمایش لیست"""
    # تعیین نوع کانفیگ برای اسکن
    query_filter = "AND type != 'sub_source'" # پیش‌فرض برای همه
    if mode == 'single':
        query_filter = "AND type='single'"
    elif mode == 'sub':
        # در حالت ساب معمولا لیست فولدرها باز میشه، اما اگر بخواهیم آیتم‌ها رو چک کنیم:
        query_filter = "AND type='sub_item'"

    # گرفتن کانفیگ‌های کاربر
    with db.get_connection() as (conn, cur):
        monitor = cur.execute("SELECT * FROM servers WHERE is_monitor_node=1 AND is_active=1").fetchone()
        # فقط ۵۰ کانفیگ آخر را برای سرعت بیشتر چک می‌کنیم (یا همه را بسته به نیاز)
        configs = cur.execute(f"SELECT * FROM tunnel_configs WHERE owner_id=? {query_filter} ORDER BY id DESC LIMIT 30", (uid,)).fetchall()

    if not monitor or not configs:
        return # چیزی برای تست نیست

    ip, port, user = monitor['ip'], monitor['port'], monitor['username']
    password = sec.decrypt(monitor['password'])
    loop = asyncio.get_running_loop()

    # پردازش دسته‌ای (Batch Processing)
    chunk_size = 5
    tasks = []
    
    for cfg in configs:
        # آماده‌سازی دستور
        link_arg = cfg['link']
        if cfg['type'] == 'json' or link_arg.strip().startswith('{'):
            safe_link = link_arg.replace('"', '\\"')
            # تست سبک (1 مگابایت) برای سرعت بالا در لیست
            cmd = f'python3 /root/monitor_agent.py "{safe_link}" 1.0'
        else:
            cmd = f"python3 /root/monitor_agent.py '{link_arg}' 1.0"
            
        # تایم‌اوت کوتاه (۱۵ ثانیه) برای عدم معطلی کاربر
        tasks.append(loop.run_in_executor(None, ServerMonitor.run_remote_command, ip, port, user, password, cmd, 15))

    # اجرای همزمان همه تست‌ها
    results = await asyncio.gather(*tasks)

    # آپدیت دیتابیس
    with db.get_connection() as (conn, cur):
        for idx, (ok, output) in enumerate(results):
            cid = configs[idx]['id']
            try:
                if ok:
                    import re
                    json_match = re.search(r'(\{.*\})', output.strip(), re.DOTALL)
                    if json_match:
                        res = json.loads(json_match.group(1))
                        if res.get("status") == "OK":
                            ping = res.get('ping', 0)
                            score = res.get('score', 0)
                            cur.execute(
                                "UPDATE tunnel_configs SET last_status='OK', last_ping=?, quality_score=? WHERE id=?",
                                (ping, score, cid)
                            )
                        else:
                            cur.execute("UPDATE tunnel_configs SET last_status='Fail' WHERE id=?", (cid,))
            except:
                pass # اگر خطا داد، وضعیت قبلی بماند یا Fail شود
        conn.commit()

# تابع جدید برای نمایش لیست بر اساس مود انتخاب شده
async def show_tunnels_by_mode(update: Update, context: ContextTypes.DEFAULT_TYPE, custom_data=None):
    query = update.callback_query
    target_data = custom_data if custom_data else query.data
    data_parts = target_data.split('_')
    mode = data_parts[2] # single, sub, all
    uid = update.effective_user.id
    
    # لاجیک صفحه بندی
    page = 1
    if len(data_parts) > 3:
        try: page = int(data_parts[3])
        except: page = 1

    delete_mode = False
    if len(data_parts) > 4:
        if data_parts[4] == '1':
            delete_mode = True
    if mode == 'sub':
        with db.get_connection() as (conn, cur):
            subs = cur.execute("SELECT * FROM tunnel_configs WHERE owner_id=? AND type='sub_source'", (uid,)).fetchall()
            
        if not subs:
            await safe_edit_message(update, "❌ هیچ اشتراکی (Subscription) ثبت نکرده‌اید.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='tunnel_list_menu')]]))
            return

        txt = "📦 **لیست اشتراک‌های شما**\nبرای مدیریت یا آپدیت روی نام اشتراک بزنید:"
        # استفاده از ماژول کیبورد
        reply_markup = keyboard.sub_list_kb(subs)
        
        await safe_edit_message(update, txt, reply_markup=reply_markup)
        return

    # --- تنظیمات کوئری برای حالت Single و All ---
    LIMIT = 10
    offset = (page - 1) * LIMIT
    
    base_query = "SELECT * FROM tunnel_configs WHERE owner_id=? AND type != 'sub_source'"
    count_query = "SELECT COUNT(*) FROM tunnel_configs WHERE owner_id=? AND type != 'sub_source'"
    params = [uid]
    
    if mode == 'single':
        base_query += " AND type='single'"
        count_query += " AND type='single'"
        title = "👤 **لیست کانفیگ‌های تکی**"
    else:
        title = "🔗 **همه کانفیگ‌ها**"

    # مرتب‌سازی بر اساس آخرین وضعیت (فعال‌ها بالا باشند)
    base_query += f" ORDER BY last_status DESC, id DESC LIMIT {LIMIT} OFFSET {offset}"
    
    with db.get_connection() as (conn, cur):
        total_count = cur.execute(count_query, params).fetchone()[0]
        configs = cur.execute(base_query, params).fetchall()

    if total_count == 0:
        await safe_edit_message(update, f"❌ موردی یافت نشد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='tunnel_list_menu')]]))
        return

    total_pages = (total_count + LIMIT - 1) // LIMIT
    
    now_time = datetime.now().strftime("%H:%M:%S")

    # --- تعیین متن پیام (وابسته به حالت حذف) ---
    if delete_mode:
        txt = (
            f"🗑 **حالت حذف فعال است**\n"
            f"⚠️ روی هر کانفیگ بزنید تا **حذف** شود:\n"
            f"📄 صفحه {page} از {total_pages}\n"
            f"➖➖➖➖➖➖➖➖➖➖"
        )
    else:
        txt = f"{title}\n🕒 آخرین تست: `{now_time}`\n📄 صفحه {page} از {total_pages}\n➖➖➖➖➖➖➖➖➖➖"
    
    # استفاده از ماژول کیبورد (با پارامتر جدید delete_mode)
    reply_markup = keyboard.tunnel_list_kb(configs, page, total_pages, mode, delete_mode=delete_mode)
    
    await safe_edit_message(update, txt, reply_markup=reply_markup)
# --- منوی مدیریت اشتراک ---
# --- منوی مدیریت اشتراک ---
async def manage_single_sub_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """منوی مدیریت اشتراک (نسخه HTML ضد کرش)"""
    query = update.callback_query
    data_parts = query.data.split('_')
    sub_id = int(data_parts[2])
    
    page = 1
    if len(data_parts) > 3 and data_parts[3].isdigit():
        page = int(data_parts[3])
    
    with db.get_connection() as (conn, cur):
        cur.execute("SELECT * FROM tunnel_configs WHERE id=%s", (sub_id,))
        sub = cur.fetchone()
        if not sub:
            await query.answer("❌ اشتراک یافت نشد.", show_alert=True)
            return
        cur.execute("SELECT id, name, last_status, last_ping FROM tunnel_configs WHERE name LIKE %s AND type='sub_item'", (f"{sub['name']}%",))
        items = cur.fetchall()

    # ✅ ایمن‌سازی نام برای HTML
    safe_sub_name = html.escape(sub['name'])

    stats_txt = ""
    try:
        if sub['sub_info'] and sub['sub_info'] != '{}':
            info = json.loads(sub['sub_info'])
            total = info.get('total', 0)
            used = info.get('upload', 0) + info.get('download', 0)
            expire_ts = info.get('expire', 0)
            
            percent = (used / total * 100) if total > 0 else 0
            bar = ServerMonitor.make_bar(percent, 10)
            
            if expire_ts:
                exp_date = datetime.fromtimestamp(expire_ts)
                days_left = (exp_date - datetime.now()).days
                exp_str = f"{days_left} روز"
            else:
                exp_str = "نامحدود"

            stats_txt = (
                f"📊 <b>وضعیت مصرف:</b>\n"
                f"💾 <code>{bar}</code> {percent:.1f}%\n"
                f"📉 مصرفی: <code>{format_bytes(used)}</code>\n"
                f"📦 کل حجم: <code>{format_bytes(total)}</code>\n"
                f"⏳ انقضا: <code>{exp_str}</code>\n"
                f"➖➖➖➖➖➖➖➖➖➖\n"
            )
    except: pass

    per_page = 8
    total_items = len(items)
    max_pages = (total_items + per_page - 1) // per_page
    start_idx = (page - 1) * per_page
    current_items = items[start_idx:start_idx + per_page]
    active_count = sum(1 for i in items if i['last_status'] == 'OK')
    
    txt = (
        f"📂 <b>مدیریت اشتراک: {safe_sub_name}</b>\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"{stats_txt}"
        f"🔢 تعداد کانفیگ: <code>{total_items}</code>\n"
        f"✅ کانفیگ‌های سالم: <code>{active_count}</code>\n\n"
        f"👇 <b>برای مشاهده جزئیات روی کانفیگ بزنید:</b>"
    )

    reply_markup = keyboard.manage_sub_kb(current_items, sub_id, page, max_pages, sub['name'])
    
    # استفاده از HTML برای جلوگیری از خطا
    await safe_edit_message(update, txt, reply_markup=reply_markup, parse_mode='HTML')


async def get_sub_links_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ارسال تمام لینک‌های یک سابسکریپشن برای کاربر به صورت فایل"""
    query = update.callback_query
    sub_id = int(query.data.split('_')[3])
    
    with db.get_connection() as (conn, cur):
        cur.execute("SELECT name FROM tunnel_configs WHERE id=%s", (sub_id,))
        sub = cur.fetchone()
        if not sub:
            await query.answer("❌ اشتراک یافت نشد.", show_alert=True)
            return
            
        cur.execute("SELECT link, name FROM tunnel_configs WHERE name LIKE %s AND type='sub_item'", (f"{sub['name']}%",))
        items = cur.fetchall()
        
    if not items:
        await query.answer("⚠️ هیچ کانفیگی در این اشتراک وجود ندارد.", show_alert=True)
        return
        
    await query.answer("📤 در حال آماده‌سازی فایل...", show_alert=False)
    
    # ساخت محتوای فایل
    file_content = ""
    for item in items:
        link = item['link']
        # اگر نیاز به تغییر نام در لینک بود اینجا اضافه می‌شود
        # فعلاً لینک خام را می‌گذاریم تا کلاینت‌ها درست کار کنند
        file_content += f"{link}\n"

    # ارسال فایل
    f = io.BytesIO(file_content.encode('utf-8'))
    f.name = f"{sub['name']}_configs.txt"
    
    try:
        await query.message.reply_document(
            document=f,
            caption=f"📦 **کانفیگ‌های اشتراک: {sub['name']}**\n🔢 تعداد: {len(items)}"
        )
    except Exception as e:
        await query.message.reply_text(f"❌ خطا در ارسال فایل: {e}")


async def delete_full_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف سابسکریپشن و تمام کانفیگ‌های زیرمجموعه (اصلاح شده)"""
    query = update.callback_query
    sub_id = int(query.data.split('_')[3])
    uid = update.effective_user.id
    
    # 1. حذف از دیتابیس
    with db.get_connection() as (conn, cur):
        cur.execute("SELECT name FROM tunnel_configs WHERE id=%s", (sub_id,))
        sub = cur.fetchone()
        if sub:
            # حذف سورس
            cur.execute("DELETE FROM tunnel_configs WHERE id=%s", (sub_id,))
            # حذف زیرمجموعه‌ها
            cur.execute("DELETE FROM tunnel_configs WHERE owner_id=%s AND name LIKE %s", (uid, f"{sub['name']}%"))
            conn.commit()
            
    # 2. نمایش پیام موفقیت (داخل try برای جلوگیری از کرش)
    try:
        await query.answer("✅ اشتراک حذف شد.", show_alert=True)
    except: pass
    
    # 3. رفرش لیست ساب‌ها (نکته مهم: استفاده از custom_data به جای تغییر query.data)
    await show_tunnels_by_mode(update, context, custom_data="list_mode_sub")
async def update_all_configs_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بروزرسانی وضعیت تمام کانفیگ‌ها به صورت یکجا"""
    query = update.callback_query
    uid = update.effective_user.id
    
    await query.answer("⏳ درخواست ارسال شد. نتیجه به تدریج بروز می‌شود.", show_alert=True)
    
    with db.get_connection() as (conn, cur):
        cur.execute("SELECT * FROM tunnel_configs WHERE owner_id=%s", (uid,))
        configs = cur.fetchall()
        cur.execute("SELECT * FROM servers WHERE is_monitor_node=1 AND is_active=1")
        monitor = cur.fetchone()

    if not monitor:
        await query.message.reply_text("❌ سرور مانیتورینگ فعال نیست.")
        return

    # اجرا در پس‌زمینه بدون معطل کردن کاربر
    asyncio.create_task(background_update_all(context, uid, configs, monitor))
    
    # بازگشت موقت به لیست
    await tunnel_list_menu(update, context)


async def background_update_all(context, uid, configs, monitor):
    """تابع پس‌زمینه برای تست همه کانفیگ‌ها"""
    ip, port, user = monitor['ip'], monitor['port'], monitor['username']
    password = sec.decrypt(monitor['password'])
    loop = asyncio.get_running_loop()

    # پردازش دسته‌ای برای سرعت (مثلا ۳ تا همزمان)
    chunk_size = 3
    for i in range(0, len(configs), chunk_size):
        chunk = configs[i:i+chunk_size]
        tasks = []
        
        for cfg in chunk:
            cmd = f"python3 /root/monitor_agent.py '{cfg['link']}'"
            if cfg['type'] == 'json':
                safe_json = cfg['link'].replace('"', '\\"')
                cmd = f'python3 /root/monitor_agent.py "{safe_json}"'
            
            tasks.append(loop.run_in_executor(None, ServerMonitor.run_remote_command, ip, port, user, password, cmd, 25))
        
        results = await asyncio.gather(*tasks)
        
        # ثبت نتایج در دیتابیس
        with db.get_connection() as (conn, cur):
            for idx, (ok, output) in enumerate(results):
                cid = chunk[idx]['id']
                try:
                    res = json.loads(output.strip())
                    if res.get("status") == "OK":
                        cur.execute(
                            "UPDATE tunnel_configs SET last_status='OK', last_ping=%s, last_jitter=%s, quality_score=%s WHERE id=%s",
                            (res.get('ping',0), res.get('jitter',0), 10, cid)
                        )
                    else:
                        cur.execute("UPDATE tunnel_configs SET last_status='Fail' WHERE id=%s", (cid,))
                except:
                    cur.execute("UPDATE tunnel_configs SET last_status='Fail' WHERE id=%s", (cid,))
            conn.commit()

    # پیام اتمام
    try:
        await context.bot.send_message(chat_id=uid, text="✅ **وضعیت تمام کانفیگ‌ها بروزرسانی شد.**")
    except: pass
async def process_add_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت لینک و تشخیص مسیر (پرسش نام برای ساب / خودکار برای تکی)"""
    link = update.message.text.strip()
    uid = update.effective_user.id
    
    # ذخیره لینک در حافظه موقت
    context.user_data['temp_link'] = link

    # --- حالت ۱: لینک سابسکریپشن (http/https) ---
    if link.startswith(('http://', 'https://')):
        context.user_data['temp_sub_link'] = link
        
        await update.message.reply_text(
            "🔗 **لینک اشتراک تشخیص داده شد.**\n\n"
            "📝 لطفاً یک **نام دلخواه** برای این اشتراک وارد کنید:\n"
            "(مثلاً: همراه اول، رادار، ...)",
            reply_markup=keyboard.get_cancel_markup()
        )
        # هدایت به مرحله دریافت نام
        return GET_SUB_NAME
    
    # --- حالت ۲: کانفیگ تکی (vmess/vless/...) ---
    elif link.startswith(('vless://', 'vmess://', 'trojan://', 'ss://')):
        # ارسال مستقیم به پردازش خودکار (بدون پرسش نام)
        return await handle_single_config_auto(update, context, link)

    else:
        await update.message.reply_text(
            "❌ **فرمت لینک شناسایی نشد!**\n"
            "لینک باید با `http` (ساب) یا `vless/vmess...` (تکی) شروع شود.",
            reply_markup=keyboard.get_cancel_markup()
        )
        return GET_CONFIG_LINKS
async def handle_config_type_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش نهایی بر اساس انتخاب کاربر (ساب یا تکی) - نسخه Non-Blocking"""
    query = update.callback_query
    choice = query.data
    link = context.user_data.get('temp_link')
    uid = update.effective_user.id
    
    await query.answer()
    
    # --- حالت ۱: سابسکریپشن ---
    if choice == 'type_sub':
        context.user_data['temp_sub_link'] = link
        await safe_edit_message(update, 
            "🔗 **حالت سابسکریپشن انتخاب شد.**\n\n"
            "📝 لطفاً یک **نام دلخواه** برای این اشتراک وارد کنید (مثلاً: همراه اول):",
            reply_markup=keyboard.get_cancel_markup()
        )
        return GET_SUB_NAME

    # --- حالت ۲: کانفیگ تکی (تسک پس‌زمینه) ---
    elif choice == 'type_single':
        # پیام اولیه (بدون انتظار طولانی برای کاربر)
        status_msg = await query.message.reply_text(
            "⏳ **در حال ارسال به صف پردازش...**\n"
            "ربات در پس‌زمینه کانفیگ را بررسی می‌کند.\n"
            "(می‌توانید با /start عملیات را لغو کنید)"
        )
        
        # تابع داخلی برای اجرای عملیات سنگین
        async def heavy_config_check():
            try:
                loop = asyncio.get_running_loop()
                
                # 1. دریافت اطلاعات سرور مانیتورینگ
                with db.get_connection() as (conn, cur):
                    cur.execute("SELECT * FROM servers WHERE is_monitor_node=1 AND is_active=1")
                    monitor = cur.fetchone()
                
                if not monitor:
                    await status_msg.edit_text("❌ سرور مانیتورینگ فعال نیست.")
                    return

                # آپدیت پیام وضعیت
                await status_msg.edit_text("🚀 **در حال تست اتصال کانفیگ...**\nلطفاً چند لحظه صبر کنید.")

                ip, port, user, password = monitor['ip'], monitor['port'], monitor['username'], sec.decrypt(monitor['password'])
                
                # دستور اجرا (با shlex برای امنیت)
                safe_link = shlex.quote(link)
                cmd = f"python3 /root/monitor_agent.py {safe_link}"
                
                # 2. اجرای دستور در ترد جداگانه (Non-Blocking)
                ok, output = await loop.run_in_executor(None, ServerMonitor.run_remote_command, ip, port, user, password, cmd, 30)
                
                # 3. تحلیل خروجی
                data = extract_safe_json(output)
                
                if ok and data:
                    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    
                    if data.get('status') == 'OK' or data.get('extracted_name') or 'protocol' in data:
                        # استخراج نام
                        final_name = data.get('extracted_name', f"Config_{int(time.time())}")
                        final_name = final_name.replace('+', ' ').strip()
                        
                        init_status = 'OK' if data.get('status') == 'OK' else 'Unknown'
                        init_ping = data.get('ping', 0)
                        score = data.get('score', 0)
                        
                        # ذخیره در دیتابیس
                        with db.get_connection() as (conn, cur):
                             cur.execute(
                                 "INSERT INTO tunnel_configs (owner_id, type, link, name, added_at, quality_score, last_status, last_ping) VALUES (%s, 'single', %s, %s, %s, %s, %s, %s)", 
                                 (uid, link, final_name, now, score, init_status, init_ping)
                             )
                             conn.commit()
                        
                        dl_spd = data.get('down', '0')
                        
                        # پیام موفقیت نهایی
                        await status_msg.edit_text(
                            f"✅ **کانفیگ تکی ذخیره شد!**\n"
                            f"🏷 نام: `{final_name}`\n"
                            f"⭐️ امتیاز: `{score}/10`\n"
                            f"🚀 سرعت دانلود: `{dl_spd} MB/s`"
                        )
                        await asyncio.sleep(2)
                        
                        # چون اینجا داخل ConversationHandler نیستیم (تسک جداست)، باید دستی منو را بفرستیم
                        kb = [[InlineKeyboardButton("🔙 بازگشت به لیست کانفیگ‌ها", callback_data='tunnel_list_menu')]]
                        await status_msg.reply_text("عملیات تکمیل شد.", reply_markup=InlineKeyboardMarkup(kb))
                        return
                
                # اگر خطا بود
                err_preview = output[:200] if output else "No Output"
                await status_msg.edit_text(f"❌ خطا: فرمت کانفیگ شناسایی نشد.\n\n⚠️ خروجی سرور:\n`{err_preview}`")

            except asyncio.CancelledError:
                await status_msg.edit_text("🚫 عملیات توسط کاربر لغو شد.")
                raise
            except Exception as e:
                await status_msg.edit_text(f"❌ خطای سیستم: {e}")
            finally:
                # حذف تسک از لیست فعال‌ها
                if uid in USER_ACTIVE_TASKS:
                    del USER_ACTIVE_TASKS[uid]

        # ✅ ایجاد و ثبت تسک
        task = asyncio.create_task(heavy_config_check())
        USER_ACTIVE_TASKS[uid] = task
        
        # پایان استیت برای کاربر (تا بتواند کارهای دیگر انجام دهد)
        return ConversationHandler.END
async def handle_single_config_auto(update: Update, context: ContextTypes.DEFAULT_TYPE, link):
    """پردازش خودکار کانفیگ تکی بدون منو"""
    uid = update.effective_user.id
    
    status_msg = await update.message.reply_text(
        "⏳ **کانفیگ تکی تشخیص داده شد...**\n"
        "🚀 در حال آنالیز، تبدیل به JSON و تست اتصال..."
    )
    
    async def heavy_config_check():
        try:
            loop = asyncio.get_running_loop()
            
            with db.get_connection() as (conn, cur):
                cur.execute("SELECT * FROM servers WHERE is_monitor_node=1 AND is_active=1")
                monitor = cur.fetchone()
            
            if not monitor:
                await status_msg.edit_text("❌ سرور مانیتورینگ فعال نیست.")
                return

            ip, port, user, password = monitor['ip'], monitor['port'], monitor['username'], sec.decrypt(monitor['password'])
            
            # دستور اجرا (ایجنت خودش نام را از # استخراج می‌کند)
            safe_link = shlex.quote(link)
            cmd = f"python3 /root/monitor_agent.py {safe_link}"
            
            ok, output = await loop.run_in_executor(None, ServerMonitor.run_remote_command, ip, port, user, password, cmd, 30)
            data = extract_safe_json(output)
            
            if ok and data and (data.get('status') == 'OK' or data.get('extracted_name')):
                now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                # دریافت نام استخراج شده توسط ایجنت
                final_name = data.get('extracted_name')
                if not final_name or final_name == "Single_Config":
                     if '#' in link:
                         try: final_name = urllib.parse.unquote(link.split('#')[-1]).strip()
                         except: pass
                
                if not final_name: final_name = f"Config_{int(time.time())}"
                final_name = final_name.replace('+', ' ').strip()

                init_status = 'OK' if data.get('status') == 'OK' else 'Unknown'
                score = data.get('score', 0)
                
                with db.get_connection() as (conn, cur):
                     cur.execute(
                         "INSERT INTO tunnel_configs (owner_id, type, link, name, added_at, quality_score, last_status, last_ping) VALUES (?, 'single', ?, ?, ?, ?, ?, ?)", 
                         (uid, link, final_name, now, score, init_status, data.get('ping', 0))
                     )
                     conn.commit()
                
                await status_msg.edit_text(
                    f"✅ **کانفیگ تکی با موفقیت افزوده شد.**\n"
                    f"🏷 نام: `{final_name}`\n"
                    f"⭐️ کیفیت: `{score}/10`"
                )
                await asyncio.sleep(2)
                
                kb = [[InlineKeyboardButton("🔙 بازگشت به لیست", callback_data='tunnel_list_menu')]]
                await status_msg.reply_text("عملیات تکمیل شد.", reply_markup=InlineKeyboardMarkup(kb))
                return
            
            await status_msg.edit_text("❌ خطا: کانفیگ معتبر نیست یا سرور ایران پاسخ نداد.")

        except Exception as e:
            await status_msg.edit_text(f"❌ خطا: {e}")
        finally:
            if uid in USER_ACTIVE_TASKS: del USER_ACTIVE_TASKS[uid]

    task = asyncio.create_task(heavy_config_check())
    USER_ACTIVE_TASKS[uid] = task
    return ConversationHandler.END
async def finalize_sub_adding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    temp_link = context.user_data.get('temp_sub_link')
    # فراخوانی لاجیک از فایل جدید
    await tunnel_manager.finalize_sub_adding(update, context, temp_link)

    # بازگشت به منو
    await tunnel_list_menu(update, context)
    return ConversationHandler.END
async def test_single_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تست دستی و دقیق (Heavy Test) یک کانفیگ با UI حرفه‌ای"""
    query = update.callback_query
    try:
        cid = int(query.data.split('_')[2])
    except:
        await query.answer("❌ خطا در دریافت شناسه کانفیگ.", show_alert=True)
        return
    
    # نمایش لودینگ روی دکمه (بدون تغییر پیام اصلی)
    try: await query.answer("🔄 آغاز تست دقیق (۱۰ مگابایت)...", cache_time=0)
    except: pass

    # 1. دریافت اطلاعات کانفیگ و سرور مانیتورینگ
    with db.get_connection() as (conn, cur):
        cur.execute("SELECT * FROM tunnel_configs WHERE id=%s", (cid,))
        cfg = cur.fetchone()
        cur.execute("SELECT * FROM servers WHERE is_monitor_node = 1 AND is_active = 1")
        monitor_node = cur.fetchone()
    
    # 2. بررسی موجود بودن
    if not cfg:
        await safe_edit_message(update, "❌ کانفیگ یافت نشد یا حذف شده است.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='tunnel_list_menu')]]))
        return

    if not monitor_node:
        await safe_edit_message(update, "❌ سرور ایران (مانیتورینگ) فعال نیست!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='tunnel_list_menu')]]))
        return

    # 3. نمایش پیام وضعیت (اگر پیام قبلی نتیجه تست نباشد)
    if "نتیجه تست دقیق" not in query.message.text:
        await safe_edit_message(
            update, 
            f"🔎 **در حال آنالیز عمیق (Heavy Test)...**\n"
            f"🏷 `{cfg['name']}`\n"
            f"⚖️ حجم تست: `10 MB` (دانلود + آپلود)\n"
            f"⏳ لطفاً تا ۶۰ ثانیه صبر کنید..."
        )
    
    # 4. آماده‌سازی اتصال SSH
    ip, port, user = monitor_node['ip'], monitor_node['port'], monitor_node['username']
    password = sec.decrypt(monitor_node['password'])
    
    # 5. ساخت دستور اجرا (با آرگومان 10.0 برای تست سنگین)
    safe_link = shlex.quote(cfg['link'])
    cmd = f"python3 -u /root/monitor_agent.py {safe_link} 10.0"
    
    loop = asyncio.get_running_loop()
    try:
        # ⚠️ افزایش تایم‌اوت به ۶۰ ثانیه برای تکمیل تست سنگین
        ok, output = await loop.run_in_executor(None, ServerMonitor.run_remote_command, ip, port, user, password, cmd, 60)
        res = extract_safe_json(output)
        if not res:
            res = {"status": "Error", "msg": "Invalid Output/Agent Crash"}
        # 7. تحلیل نتایج و نمایش گزارش
        if res.get("status") == "OK":
            ping = res.get('ping', 0)
            jitter = res.get('jitter', 0)
            up = res.get('up', '0')
            down = res.get('down', '0')
            score = res.get('score', 0)
            
            # تعیین آیکون کیفیت بر اساس امتیاز
            if score >= 8: q_icon = "💎 عالی"
            elif score >= 5: q_icon = "⚖️ معمولی"
            else: q_icon = "⚠️ ضعیف"
            
            # آپدیت دیتابیس با مقادیر واقعی تست سنگین
            with db.get_connection() as (conn, cur):
                cur.execute(
                    "UPDATE tunnel_configs SET last_status='OK', last_ping=?, last_jitter=?, last_speed_up=?, last_speed_down=?, quality_score=? WHERE id=?",
                    (ping, jitter, up, down, score, cid)
                )
                conn.commit()
            
            report = (
                f"✅ **نتیجه تست دقیق (Heavy)** 🟢\n"
                f"➖➖➖➖➖➖➖➖➖➖\n"
                f"🏷 نام: `{cfg['name']}`\n"
                f"🛡 امتیاز کیفی: `{score}/10` ({q_icon})\n\n"
                f"📶 **Ping:** `{ping} ms`\n"
                f"📉 **Jitter:** `{jitter} ms`\n"
                f"📥 **Download:** `{down} MB/s`\n"
                f"📤 **Upload:** `{up} MB/s`"
            )
        else:
            # ثبت خطا در دیتابیس
            with db.get_connection() as (conn, cur):
                cur.execute("UPDATE tunnel_configs SET last_status='Fail', quality_score=0 WHERE id=?", (cid,))
                conn.commit()
            
            error_msg = res.get('msg', 'Timeout/Filtering')
            report = (
                f"⛔️ **عدم برقراری ارتباط** 🔴\n"
                f"➖➖➖➖➖➖➖➖➖➖\n"
                f"🏷 نام: `{cfg['name']}`\n\n"
                f"❌ خطا: `{error_msg}`\n"
                f"💡 _ممکن است سرور پاسخ ندهد، تایم‌اوت شده باشد یا آی‌پی فیلتر باشد._"
            )
            
    except Exception as e:
        report = f"❌ خطای سیستمی در اجرای تست:\n`{e}`"

    # استفاده از ماژول کیبورد
    reply_markup = keyboard.config_test_result_kb(cid)
    
    await safe_edit_message(update, report, reply_markup=reply_markup, parse_mode='Markdown')

async def view_config_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش کد خام کانفیگ به کاربر"""
    query = update.callback_query
    cid = int(query.data.split('_')[2])
    
    with db.get_connection() as (conn, cur):
        cur.execute("SELECT * FROM tunnel_configs WHERE id=%s", (cid,))
        cfg = cur.fetchone()
        
    if not cfg:
        await query.answer("❌ کانفیگ یافت نشد.", show_alert=True)
        return

    content = cfg['link']
    
    # اگر جیسون بود، مرتبش کن
    if cfg['type'] == 'json':
        try:
            parsed = json.loads(content)
            content = json.dumps(parsed, indent=2)
        except: pass

    # اگر خیلی طولانی بود فایل بده، وگرنه متن
    if len(content) > 4000:
        f = io.BytesIO(content.encode())
        f.name = f"{cfg['name']}.json" if cfg['type'] == 'json' else "config.txt"
        await query.message.reply_document(document=f, caption="📄 فایل کانفیگ")
    else:
        # ارسال در قالب کد برای کپی راحت
        await query.message.reply_text(f"📝 **کد کانفیگ:**\n\n`{content}`", parse_mode='Markdown')
    
    try: await query.answer()
    except: pass

async def delete_config_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    cid = int(query.data.split('_')[2])
    uid = update.effective_user.id

    db.delete_tunnel_config(cid, uid)

    await query.answer("✅ کانفیگ حذف شد.")
    await tunnel_list_menu(update, context)
# ==============================================================================
# 🧩 MISSING FUNCTIONS (ADDED TO FIX CRASH)
# ==============================================================================

async def advanced_monitoring_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """منوی تنظیمات پیشرفته مانیتورینگ"""
    uid = update.effective_user.id
    if update.callback_query:
        await update.callback_query.answer()
        
    s_size = db.get_setting(uid, 'monitor_small_size') or '0.5'
    b_size = db.get_setting(uid, 'monitor_big_size') or '10'
    
    # استفاده از کیبورد موجود در keyboard.py
    reply_markup = keyboard.advanced_monitor_kb(s_size, b_size)
    txt = (
        "⚙️ **تنظیمات پیشرفته مانیتورینگ تانل**\n"
        "➖➖➖➖➖➖➖➖➖➖\n"
        "🔹 **تست سبک:** هر ۱۰ دقیقه برای بررسی پینگ و اتصال (کم‌مصرف).\n"
        "🔸 **تست سنگین:** هر چند ساعت برای بررسی دقیق سرعت و کیفیت.\n\n"
        "👇 مقادیر مورد نظر را تغییر دهید:"
    )
    await safe_edit_message(update, txt, reply_markup=reply_markup)

async def set_small_size_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    curr = db.get_setting(uid, 'monitor_small_size') or '0.5'
    reply_markup = keyboard.monitor_size_kb(curr, 'small')
    await safe_edit_message(update, "🔹 حجم دانلود برای **تست سبک** (Ping Check):", reply_markup=reply_markup)

async def set_big_size_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    curr = db.get_setting(uid, 'monitor_big_size') or '10'
    reply_markup = keyboard.monitor_size_kb(curr, 'big')
    await safe_edit_message(update, "🔸 حجم دانلود برای **تست سنگین** (Speed Test):", reply_markup=reply_markup)

async def set_big_interval_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    curr = db.get_setting(uid, 'monitor_big_interval') or '60'
    reply_markup = keyboard.monitor_interval_kb(curr)
    await safe_edit_message(update, "⏰ فاصله زمانی اجرای **تست سنگین**:", reply_markup=reply_markup)

async def save_setting_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = update.effective_user.id
    data = query.data # e.g., save_small_0.5, save_int_60
    
    parts = data.split('_')
    setting_type = parts[1] # small, big, int
    value = parts[2]
    
    if value == 'custom':
        map_txt = {'small': "✍️ حجم تست سبک (MB) را وارد کنید:", 'big': "✍️ حجم تست سنگین (MB) را وارد کنید:", 'int': "✍️ فاصله زمانی (دقیقه) را وارد کنید:"}
        state_map = {'small': GET_CUSTOM_SMALL_SIZE, 'big': GET_CUSTOM_BIG_SIZE, 'int': GET_CUSTOM_BIG_INTERVAL}
        
        await safe_edit_message(update, map_txt[setting_type], reply_markup=keyboard.get_cancel_markup())
        return state_map[setting_type]
    
    key_map = {'small': 'monitor_small_size', 'big': 'monitor_big_size', 'int': 'monitor_big_interval'}
    db.set_setting(uid, key_map[setting_type], value)
    
    await query.answer("✅ ذخیره شد.")
    await advanced_monitoring_settings(update, context)

async def custom_small_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = float(update.message.text)
        db.set_setting(update.effective_user.id, 'monitor_small_size', val)
        await update.message.reply_text("✅ ذخیره شد.")
        await advanced_monitoring_settings(update, context)
        return ConversationHandler.END
    except:
        await update.message.reply_text("❌ عدد نامعتبر.")
        return GET_CUSTOM_SMALL_SIZE

async def custom_big_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = float(update.message.text)
        db.set_setting(update.effective_user.id, 'monitor_big_size', val)
        await update.message.reply_text("✅ ذخیره شد.")
        await advanced_monitoring_settings(update, context)
        return ConversationHandler.END
    except:
        await update.message.reply_text("❌ عدد نامعتبر.")
        return GET_CUSTOM_BIG_SIZE

async def custom_int_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = int(update.message.text)
        db.set_setting(update.effective_user.id, 'monitor_big_interval', val)
        await update.message.reply_text("✅ ذخیره شد.")
        await advanced_monitoring_settings(update, context)
        return ConversationHandler.END
    except:
        await update.message.reply_text("❌ عدد نامعتبر.")
        return GET_CUSTOM_BIG_INTERVAL

async def show_config_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش جزئیات یک کانفیگ خاص"""
    query = update.callback_query
    try:
        cid = int(query.data.split('_')[2])
    except:
        await query.answer("❌ خطا در شناسه کانفیگ")
        return

    with db.get_connection() as (conn, cur):
        cur.execute("SELECT * FROM tunnel_configs WHERE id=%s", (cid,))
        cfg = cur.fetchone()
        
    if not cfg:
        try: await query.answer("❌ کانفیگ یافت نشد یا حذف شده است.", show_alert=True)
        except: pass
        # رفرش لیست
        await tunnel_list_menu(update, context)
        return

    # تلاش برای پیدا کردن آیدی والد (اگر ساب آیتم باشد) برای دکمه بازگشت
    parent_id = None
    if cfg['type'] == 'sub_item':
        if " | " in cfg['name']:
            sub_name = cfg['name'].split(" | ")[0]
            with db.get_connection() as (conn, cur):
                cur.execute("SELECT id FROM tunnel_configs WHERE name=%s AND type='sub_source'", (sub_name,))
                parent = cur.fetchone()
                if parent:
                    parent_id = parent['id']

    status_icon = "🟢" if cfg['last_status'] == 'OK' else "🔴"
    ping_txt = f"{cfg['last_ping']} ms" if cfg['last_ping'] > 0 else "N/A"
    
    txt = (
        f"🏷 **جزئیات کانفیگ**\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"📝 **نام:** `{cfg['name']}`\n"
        f"📡 **وضعیت:** {status_icon} `{cfg['last_status']}`\n"
        f"📶 **پینگ:** `{ping_txt}`\n"
        f"🛡 **امتیاز کیفی:** `{cfg['quality_score']}/10`\n\n"
        f"📅 تاریخ ثبت: `{cfg['added_at']}`"
    )

    # استفاده از کیبورد موجود در keyboard.py
    reply_markup = keyboard.config_detail_kb(cid, parent_id)
    
    await safe_edit_message(update, txt, reply_markup=reply_markup)

async def copy_config_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """کپی کردن لینک کانفیگ"""
    query = update.callback_query
    cid = int(query.data.split('_')[2])
    
    with db.get_connection() as (conn, cur):
        cur.execute("SELECT link FROM tunnel_configs WHERE id=%s", (cid,))
        cfg = cur.fetchone()
        
    if cfg:
        await query.message.reply_text(f"`{cfg['link']}`", parse_mode='Markdown')
        await query.answer("✅ لینک کانفیگ ارسال شد.")
    else:
        await query.answer("❌ کانفیگ پیدا نشد.", show_alert=True)

async def qr_config_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش QR Code کانفیگ"""
    query = update.callback_query
    cid = int(query.data.split('_')[2])
    
    with db.get_connection() as (conn, cur):
        cur.execute("SELECT link, name FROM tunnel_configs WHERE id=%s", (cid,))
        cfg = cur.fetchone()

    if not cfg:
        await query.answer("❌ کانفیگ پیدا نشد.", show_alert=True)
        return

    await query.answer("🔄 در حال ایجاد QR Code...")
    try:
        encoded_link = urllib.parse.quote(cfg['link'])
        qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=400x400&data={encoded_link}"
        
        await query.message.reply_photo(
            photo=qr_url, 
            caption=f"🔲 **QR Code:**\n`{cfg['name']}`",
            parse_mode='Markdown'
        )
    except Exception as e:
        await query.message.reply_text(f"❌ امکان ارسال عکس وجود ندارد.\nلینک:\n`{cfg['link']}`", parse_mode='Markdown')


async def manual_update_sub_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بروزرسانی دستی یک اشتراک خاص"""
    query = update.callback_query
    sub_id = int(query.data.split('_')[2])
    
    await query.answer("⏳ درخواست آپدیت ثبت شد...", show_alert=True)
    
    with db.get_connection() as (conn, cur):
        cur.execute("SELECT * FROM tunnel_configs WHERE id=%s", (sub_id,))
        sub = cur.fetchone()
        cur.execute("SELECT * FROM servers WHERE is_monitor_node=1 AND is_active=1")
        monitor = cur.fetchone()
    
    if not sub or sub['type'] != 'sub_source':
        try: await query.message.reply_text("❌ اشتراک یافت نشد.")
        except: pass
        return

    if not monitor:
        try: await query.message.reply_text("❌ سرور مانیتورینگ فعال نیست.")
        except: pass
        return

    asyncio.create_task(run_sub_update_background(context, update.effective_user.id, sub['link'], sub['name'], sub_id, monitor))

async def run_sub_update_background(context, uid, link, sub_name, sub_id, monitor):
    try:
        # اطلاع‌رسانی اولیه
        try:
            await context.bot.send_message(uid, f"🔄 **فرآیند آپدیت اشتراک {sub_name} آغاز شد...**\n⏳ در حال پاکسازی قدیمی‌ها و دریافت لیست جدید...")
        except: pass

        # 1. پاکسازی کانفیگ‌های قدیمی این اشتراک (بسیار مهم برای جلوگیری از تکرار)
        with db.get_connection() as (conn, cur):
            # حذف تمام زیرمجموعه‌های قبلی که تایپشان sub_item است و نامشان با اسم اشتراک شروع می‌شود
            cur.execute("DELETE FROM tunnel_configs WHERE owner_id=%s AND name LIKE %s AND type='sub_item'", (uid, f"{sub_name} | %"))
            conn.commit()

        ip, port, user = monitor['ip'], monitor['port'], monitor['username']
        password = sec.decrypt(monitor['password'])
        
        # استفاده از فلگ -u برای دریافت خروجی لحظه‌ای
        cmd = f"python3 -u /root/monitor_agent.py '{link}'"
        
        client = ServerMonitor.get_ssh_client(ip, port, user, password)
        stdin, stdout, stderr = client.exec_command(cmd, get_pty=True)
        
        new_count = 0
        active_count = 0
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # خواندن خروجی خط به خط
        for line in iter(stdout.readline, ""):
            line = line.strip()
            if not line: continue
            
            import re
            json_match = re.search(r'(\{.*\})', line)
            if json_match:
                try:
                    data = json.loads(json_match.group(1))
                    
                    # الف) آپدیت اطلاعات حجم (Meta)
                    if data.get('type') == 'meta' and 'sub_info' in data:
                        info_str = json.dumps(data['sub_info'])
                        with db.get_connection() as (conn, cur):
                            cur.execute("UPDATE tunnel_configs SET sub_info=%s WHERE id=%s", (info_str, sub_id))
                            conn.commit()
                            
                    # ب) افزودن کانفیگ‌های جدید (Result)
                    elif data.get('type') == 'result':
                        conf_link = data.get('link')
                        name = data.get('name', 'Unknown')
                        status = data.get('status')
                        ping = data.get('ping', 0) # دریافت پینگ لحظه‌ای
                        
                        # محاسبه کیفیت و امتیاز
                        quality = 10
                        if status != 'OK':
                            quality = 0
                        elif ping > 1000:
                            quality = 3
                        elif ping > 500:
                            quality = 6
                        
                        if status == 'OK': active_count += 1

                        # نام نهایی ترکیبی
                        final_name = f"{sub_name} | {name}"
                        
                        with db.get_connection() as (conn, cur):
                            # درج مستقیم (چون قبلاً قدیمی‌ها را پاک کردیم، نیازی به چک کردن تکراری نیست مگر لینک دقیقاً یکی باشد)
                            cur.execute(
                                """INSERT INTO tunnel_configs (owner_id, type, link, name, added_at, quality_score, last_status, last_ping) 
                                   VALUES (%s, 'sub_item', %s, %s, %s, %s, %s, %s) 
                                   ON CONFLICT(link) DO UPDATE SET last_status=excluded.last_status, last_ping=excluded.last_ping""",
                                (uid, conf_link, final_name, now, quality, status, ping)
                            )
                            new_count += 1
                            conn.commit()
                except: pass
        
        client.close()
        
        # ارسال گزارش نهایی شیک
        msg = (
            f"✅ **آپدیت اشتراک {sub_name} تکمیل شد.**\n"
            f"➖➖➖➖➖➖➖➖➖➖\n"
            f"📥 **تعداد کل دریافت شده:** `{new_count}`\n"
            f"🟢 **کانفیگ‌های سالم:** `{active_count}`\n"
            f"🗑 کانفیگ‌های منقضی شده حذف شدند."
        )
            
        try:
            await context.bot.send_message(uid, msg, parse_mode='Markdown')
        except: pass

    except Exception as e:
        logger.error(f"Sub Update Error: {e}")
        try: await context.bot.send_message(uid, f"❌ خطا در آپدیت: {e}")
        except: pass
async def delete_item_from_list_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف آیتم و رفرش کردن صحیح لیست"""
    query = update.callback_query
    parts = query.data.split('_')
    # فرمت: del_list_item_{id}_{mode}_{page}
    
    cid = int(parts[3])
    mode = parts[4]
    page = int(parts[5])
    uid = update.effective_user.id
    
    # 1. حذف از دیتابیس
    db.delete_tunnel_config(cid, uid)
    
    try:
        await query.answer("🗑 حذف شد.", show_alert=False)
    except: pass
    
    # 2. محاسبه اینکه آیا صفحه فعلی هنوز آیتم دارد یا خیر
    # اگر آخرین آیتم صفحه را حذف کرده باشیم، باید به صفحه قبل برویم
    with db.get_connection() as (conn, cur):
        # شمارش آیتم‌های باقی‌مانده
        base_query = "SELECT COUNT(*) FROM tunnel_configs WHERE owner_id=%s AND type != 'sub_source'"
        if mode == 'single':
            base_query += " AND type='single'"
        
        cur.execute(base_query, (uid,))
        total_count = cur.fetchone()[0]
    
    LIMIT = 10
    total_pages = (total_count + LIMIT - 1) // LIMIT
    
    # اگر صفحه‌ای که توش بودیم دیگه وجود نداره (مثلا صفحه ۲ بودیم و آیتم‌ها کم شد و شد ۱ صفحه)
    # به آخرین صفحه موجود برمی‌گردیم
    if page > total_pages and total_pages > 0:
        page = total_pages
    elif total_pages == 0:
        page = 1 # اگر کلا خالی شد

    # 3. بازسازی کال‌بک برای رفرش کردن لیست
    # state=1 یعنی در حالت حذف باقی بمان
    new_data = f"list_mode_{mode}_{page}_1"
    
    # فراخوانی تابع نمایش
    await show_tunnels_by_mode(update, context, custom_data=new_data)
# ==============================================================================
# 🚀 MASS UPDATE & HEAVY TEST LOGIC (UPDATED WITH SINGLES)
# ==============================================================================

async def mass_update_test_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع عملیات بروزرسانی همگانی و تست دقیق (ضد کرش)"""
    logger.info("🚀 Mass Update Triggered")
    query = update.callback_query
    uid = update.effective_user.id
    
    # 1. پاسخ به دکمه (با محافظت ضد کرش)
    try:
        await query.answer("🚀 عملیات آغاز شد...", show_alert=False)
    except Exception as e:
        logger.warning(f"Callback answer ignored in mass update: {e}")

    # 2. دریافت اطلاعات از دیتابیس
    try:
        with db.get_connection() as (conn, cur):
            # دریافت ساب‌ها
            cur.execute("SELECT * FROM tunnel_configs WHERE owner_id=%s AND type='sub_source'", (uid,))
            subs = cur.fetchall()
            # دریافت کانفیگ‌های تکی
            cur.execute("SELECT * FROM tunnel_configs WHERE owner_id=%s AND type='single'", (uid,))
            singles = cur.fetchall()
            # دریافت سرور مانیتورینگ
            cur.execute("SELECT * FROM servers WHERE is_monitor_node=1 AND is_active=1")
            monitor = cur.fetchone()

        # بررسی اینکه آیا اصلا چیزی برای تست هست؟
        if not subs and not singles:
            await query.message.reply_text("❌ هیچ اشتراک یا کانفیگ تکی ندارید.")
            return

        if not monitor:
            await query.message.reply_text("❌ سرور مانیتورینگ (Iran Node) فعال نیست.")
            return
        
        status_msg = await query.message.reply_text(
            f"⏳ **در حال آماده‌سازی برای تست همگانی...**\n"
            f"📦 تعداد ساب‌ها: `{len(subs)}`\n"
            f"👤 تعداد تکی‌ها: `{len(singles)}`\n"
            f"📡 سرور تست: `{monitor['name']}`\n\n"
            f"لطفاً صبر کنید..."
        )

        # اجرای عملیات سنگین در پس‌زمینه
        # نکته: مطمئن شوید tunnel_manager در بالای فایل ایمپورت شده باشد
        asyncio.create_task(tunnel_manager.run_mass_update_process(context, uid, subs, singles, monitor, status_msg))
    
    except Exception as e:
        logger.error(f"Error in mass_update_test_start: {e}")
        await context.bot.send_message(chat_id=uid, text=f"❌ خطای داخلی: {e}")
async def show_add_service_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش منوی انتخاب افزودن سرویس"""
    if update.callback_query:
        await update.callback_query.answer()
    
    txt = (
        "➕ **افزودن سرویس جدید**\n\n"
        "لطفاً نوع سرویسی که می‌خواهید اضافه کنید را انتخاب نمایید:"
    )
    # فراخوانی کیبورد جدید
    reply_markup = keyboard.add_service_selection_kb()
    await safe_edit_message(update, txt, reply_markup=reply_markup)

async def show_lists_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش منوی انتخاب لیست‌ها"""
    if update.callback_query:
        await update.callback_query.answer()
    
    txt = (
        "📂 **مدیریت لیست‌ها**\n\n"
        "لطفاً انتخاب کنید کدام لیست را می‌خواهید مشاهده کنید:"
    )
    # فراخوانی کیبورد جدید
    reply_markup = keyboard.lists_dashboard_kb()
    await safe_edit_message(update, txt, reply_markup=reply_markup)
async def show_account_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش اطلاعات حساب کاربری و کیف پول به صورت یکجا"""
    if update.callback_query:
        await update.callback_query.answer()
    
    uid = update.effective_user.id
    user = db.get_user(uid)
    
    # محاسبات تاریخ و نوع اکانت
    try:
        join_date = datetime.strptime(user['added_date'], '%Y-%m-%d %H:%M:%S')
        j_join = jdatetime.date.fromgregorian(date=join_date.date())
        join_str = f"{j_join.day} {jdatetime.date.j_months_fa[j_join.month - 1]} {j_join.year}"
    except:
        join_str = "نامشخص"

    access, time_left = db.check_access(uid, SUPER_ADMIN_ID)
    if uid == SUPER_ADMIN_ID:
        sub_type = "👑 مدیریت کل"
        expiry_str = "♾ نامحدود"
    else:
        sub_type = "💎 پریمیوم (VIP)" if user['plan_type'] == 1 else "👤 عادی"
        expiry_str = f"{time_left} روز مانده" if isinstance(time_left, int) else "نامحدود"

    # آمار سرورها
    servers = db.get_all_user_servers(uid)
    active_srv = sum(1 for s in servers if s['is_active'])
    
    # ✅ اصلاح شده: دریافت موجودی بدون استفاده از .get()
    balance = user['wallet_balance'] if user['wallet_balance'] else 0

    txt = (
        f"👤 **داشبورد حساب کاربری**\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"🏷 **نام:** `{user['full_name']}`\n"
        f"🆔 **شناسه:** `{user['user_id']}`\n"
        f"📅 **عضویت:** `{join_str}`\n\n"
        
        f"💳 **وضعیت اشتراک:**\n"
        f"   ├ نوع: {sub_type}\n"
        f"   ├ اعتبار: `{expiry_str}`\n"
        f"   └ لیمیت سرور: `{user['server_limit']} عدد`\n\n"
        
        f"💰 **کیف پول:**\n"
        f"   └ موجودی: `{balance:,} تومان`\n\n"
        
        f"🖥 **سرورهای فعال:** `{active_srv}` از `{len(servers)}`"
    )

    reply_markup = keyboard.account_dashboard_kb()
    await safe_edit_message(update, txt, reply_markup=reply_markup)
async def refresh_conf_dash_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اجرای تست سبک (پینگ) برای همه کانفیگ‌ها و بازگشت به داشبورد"""
    query = update.callback_query
    uid = update.effective_user.id
    
    # نمایش پیام موقت
    try: await query.answer("🚀 در حال تست پینگ همگانی...", cache_time=1)
    except: pass
    
    status_msg = await query.message.reply_text(
        "⏳ **در حال بروزرسانی وضعیت (Ping Only)...**\n"
        "سرعت این عملیات بالاست، لطفاً صبر کنید."
    )
    
    with db.get_connection() as (conn, cur):
        cur.execute("SELECT * FROM tunnel_configs WHERE owner_id=%s", (uid,))
        configs = cur.fetchall()
        cur.execute("SELECT * FROM servers WHERE is_monitor_node=1 AND is_active=1")
        monitor = cur.fetchone()

    if not monitor:
        await status_msg.edit_text("❌ سرور مانیتورینگ فعال نیست.")
        return

    # اجرای عملیات در پس‌زمینه (نسخه اصلاح شده Ping Only)
    await run_quick_ping_check(context, uid, configs, monitor)
    
    # حذف پیام انتظار
    try: await status_msg.delete()
    except: pass
    
    # بازگشت خودکار به داشبورد بروز شده
    await config_stats_dashboard(update, context)

async def run_quick_ping_check(context, uid, configs, monitor):
    """لاجیک تست بسیار سریع و سبک (فقط پینگ)"""
    ip, port, user = monitor['ip'], monitor['port'], monitor['username']
    password = sec.decrypt(monitor['password'])
    loop = asyncio.get_running_loop()

    # پردازش دسته‌ای (۵ تایی) برای سرعت بالا
    chunk_size = 5
    for i in range(0, len(configs), chunk_size):
        chunk = configs[i:i+chunk_size]
        tasks = []
        
        for cfg in chunk:
            # ارسال سایز 0.2 مگابایت فقط برای هندشیک و پینگ (بسیار سبک)
            # و تایم اوت کوتاه (۱۰ ثانیه)
            link_arg = cfg['link']
            if cfg['type'] == 'json' or link_arg.strip().startswith('{'):
                safe_link = link_arg.replace('"', '\\"')
                cmd = f'python3 /root/monitor_agent.py "{safe_link}" 0.2'
            else:
                cmd = f"python3 /root/monitor_agent.py '{link_arg}' 0.2"
            
            tasks.append(loop.run_in_executor(None, ServerMonitor.run_remote_command, ip, port, user, password, cmd, 10))
        
        results = await asyncio.gather(*tasks)
        
        with db.get_connection() as (conn, cur):
            for idx, (ok, output) in enumerate(results):
                cid = chunk[idx]['id']
                try:
                    res = extract_safe_json(output)
                    if res and res.get("status") == "OK":
                        # محاسبه امتیاز فقط بر اساس پینگ و جیتر (چون سرعت تست نشده)
                        ping = res.get('ping', 0)
                        jitter = res.get('jitter', 0)
                        
                        # فرمول ساده امتیازدهی پینگ
                        new_score = 10
                        if ping > 1000: new_score = 2
                        elif ping > 500: new_score = 5
                        elif ping > 200: new_score = 8
                        
                        cur.execute(
                            "UPDATE tunnel_configs SET last_status='OK', last_ping=?, last_jitter=?, quality_score=? WHERE id=?",
                            (ping, jitter, new_score, cid)
                        )
                    else:
                        cur.execute("UPDATE tunnel_configs SET last_status='Fail' WHERE id=?", (cid,))
                except:
                    cur.execute("UPDATE tunnel_configs SET last_status='Fail' WHERE id=?", (cid,))
            conn.commit()
# ==============================================================================
# 🧩 MISSING FUNCTIONS (توابع گم‌شده)
# ==============================================================================

async def manual_ping_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع پینگ دستی"""
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "🌐 **آدرس مورد نظر (IP یا دامنه) را ارسال کنید:**", 
        reply_markup=keyboard.get_cancel_markup()
    )
    return GET_MANUAL_HOST

async def perform_manual_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اجرای پینگ دستی"""
    target = update.message.text
    msg = await update.message.reply_text(f"⏳ **در حال تست پینگ {target}...**")
    loop = asyncio.get_running_loop()
    # استفاده از API چک هاست که در core موجود است
    ok, data = await loop.run_in_executor(None, ServerMonitor.check_host_api, target)
    if ok:
        # استفاده از فرمت‌دهی موجود در StatsManager
        res = StatsManager.format_check_host_results(data)
        await msg.edit_text(res, parse_mode='Markdown')
    else:
        await msg.edit_text(f"❌ خطا در دریافت اطلاعات: {data}")
    return ConversationHandler.END

async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش منوی تنظیمات"""
    if update.callback_query: await update.callback_query.answer()
    reply_markup = keyboard.settings_main_kb()
    await safe_edit_message(update, "⚙️ **تنظیمات پیشرفته:**", reply_markup=reply_markup)

async def wallet_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش منوی کیف پول"""
    if update.callback_query: await update.callback_query.answer()
    reply_markup = keyboard.wallet_main_kb()
    await safe_edit_message(update, "💳 **کیف پول و خرید اشتراک:**", reply_markup=reply_markup)

async def select_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """انتخاب روش پرداخت"""
    plan_key = update.callback_query.data.split('_')[2]
    context.user_data['selected_plan'] = plan_key
    reply_markup = keyboard.payment_method_kb()
    await safe_edit_message(update, "💳 لطفاً روش پرداخت را انتخاب کنید:", reply_markup=reply_markup)

async def channels_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت کانال‌ها"""
    if update.callback_query: await update.callback_query.answer()
    channels = db.get_user_channels(update.effective_user.id)
    kb = []
    for ch in channels:
        kb.append([InlineKeyboardButton(f"🗑 حذف: {ch['name']}", callback_data=f"delchan_{ch['id']}")])
    kb.append([InlineKeyboardButton("➕ افزودن کانال جدید", callback_data='add_channel')])
    kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data='settings_menu')])
    await safe_edit_message(update, "📢 **مدیریت کانال‌های متصل:**", reply_markup=InlineKeyboardMarkup(kb))

async def schedules_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """منوی زمان‌بندی‌ها"""
    if update.callback_query: await update.callback_query.answer()
    uid = update.effective_user.id
    # دریافت تنظیمات فعلی برای نمایش تیک
    srv_alert = "✅" if db.get_setting(uid, 'down_alert_enabled') == '1' else "❌"
    conf_alert = "✅" if (db.get_setting(uid, 'config_alert_enabled') or '1') == '1' else "❌"
    
    # مقادیر toggle (برای دکمه بعدی)
    srv_toggle = '0' if srv_alert == "✅" else '1'
    conf_toggle = '0' if conf_alert == "✅" else '1'
    
    reply_markup = keyboard.schedules_settings_kb(srv_alert, srv_toggle, conf_alert, conf_toggle)
    await safe_edit_message(update, "⏰ **تنظیمات زمان‌بندی و هشدارها:**", reply_markup=reply_markup)

async def settings_cron_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """منوی زمان‌بندی گزارش سرور"""
    uid = update.effective_user.id
    curr = db.get_setting(uid, 'report_interval') or '0'
    reply_markup = keyboard.settings_cron_kb(curr)
    await safe_edit_message(update, "📊 **زمان‌بندی گزارش وضعیت سرورها:**", reply_markup=reply_markup)

async def config_cron_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """منوی زمان‌بندی گزارش کانفیگ"""
    uid = update.effective_user.id
    curr = db.get_setting(uid, 'config_report_interval') or '60'
    reply_markup = keyboard.config_cron_kb(curr)
    await safe_edit_message(update, "📡 **زمان‌بندی گزارش وضعیت کانفیگ‌ها:**", reply_markup=reply_markup)

async def toggle_config_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تغییر وضعیت هشدار کانفیگ"""
    state = update.callback_query.data.split('_')[2]
    db.set_setting(update.effective_user.id, 'config_alert_enabled', state)
    await schedules_settings_menu(update, context)

async def send_general_report_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ارسال گزارش کلی دستی"""
    await update.callback_query.answer("⏳ در حال تولید گزارش...")
    await cronjobs.global_monitor_job(context) # اجرای دستی جاب
    await update.callback_query.message.reply_text("✅ گزارش کلی به کانال‌های تنظیم شده ارسال شد.")

async def manage_servers_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لیست مدیریت خاموش/روشن کردن مانیتورینگ"""
    servers = db.get_all_user_servers(update.effective_user.id)
    reply_markup = keyboard.manage_monitor_list_kb(servers)
    await safe_edit_message(update, "⚡️ **برای تغییر وضعیت مانیتورینگ روی سرور بزنید:**", reply_markup=reply_markup)

async def toggle_server_active_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تغییر وضعیت فعال/غیرفعال سرور"""
    sid = int(update.callback_query.data.split('_')[2])
    srv = db.get_server_by_id(sid)
    if srv:
        new_state = db.toggle_server_active(sid, srv['is_active'])
        state_str = "غیرفعال 🔴" if new_state == 0 else "فعال 🟢"
        await update.callback_query.answer(f"سرور {srv['name']} {state_str} شد.")
        await manage_servers_list(update, context)

async def header_none_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """برای دکمه‌های هدر که عملی ندارند"""
    await update.callback_query.answer()

async def config_stats_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """داشبورد وضعیت کانفیگ‌ها"""
    if update.callback_query: await update.callback_query.answer()
    
    uid = update.effective_user.id
    # آمار کلی
    with db.get_connection() as (conn, cur):
        total = cur.execute("SELECT COUNT(*) FROM tunnel_configs WHERE owner_id=?", (uid,)).fetchone()[0]
        active = cur.execute("SELECT COUNT(*) FROM tunnel_configs WHERE owner_id=? AND last_status='OK'", (uid,)).fetchone()[0]
        subs = cur.execute("SELECT COUNT(*) FROM tunnel_configs WHERE owner_id=? AND type='sub_source'", (uid,)).fetchone()[0]

    inactive = total - active - subs # ساب‌ها را از کل کم می‌کنیم چون وضعیتشان مهم نیست
    
    txt = (
        f"📡 **وضعیت شبکه و کانفیگ‌ها**\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"📦 تعداد سابسکریپشن: `{subs}`\n"
        f"👤 کانفیگ‌های تکی و آیتم‌ها: `{total - subs}`\n\n"
        f"✅ **آنلاین:** `{active}`\n"
        f"🔴 **آفلاین:** `{inactive}`"
    )
    
    kb = [
        [InlineKeyboardButton("🔄 تست پینگ همگانی (Fast)", callback_data='refresh_conf_dash_ping')],
        [InlineKeyboardButton("🔙 بازگشت", callback_data='status_dashboard')]
    ]
    await safe_edit_message(update, txt, reply_markup=InlineKeyboardMarkup(kb))

async def set_dns_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تنظیم DNS سرور"""
    query = update.callback_query
    parts = query.data.split('_')
    dns_type = parts[1]
    sid = parts[2]
    
    srv = db.get_server_by_id(sid)
    if not srv:
        await query.answer("❌ سرور یافت نشد.")
        return

    await query.message.reply_text(f"⚙️ **در حال تنظیم DNS {dns_type} روی سرور...**")
    
    real_pass = sec.decrypt(srv['password'])
    loop = asyncio.get_running_loop()
    
    ok, msg = await loop.run_in_executor(None, ServerMonitor.set_dns, srv['ip'], srv['port'], srv['username'], real_pass, dns_type)
    
    if ok:
        await query.message.reply_text("✅ **DNS با موفقیت تغییر کرد.**")
    else:
        await query.message.reply_text(f"❌ خطا در تغییر DNS:\n{msg}")
    
    await server_detail(update, context, custom_sid=sid)

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /setting"""
    await settings_menu(update, context)

# ==============================================================================
# END OF MISSING FUNCTIONS
# ==============================================================================
def main():
    print("🚀 SONAR ULTRA PRO RUNNING...")
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .connect_timeout(60.0)  # 60 ثانیه انتظار برای اتصال (بهینه برای شبکه ایران)
        .read_timeout(60.0)     # 60 ثانیه انتظار برای دریافت پاسخ
        .write_timeout(60.0)    # 60 ثانیه انتظار برای ارسال
        .build()
    )
    app.add_error_handler(error_handler)

    text_filter = filters.TEXT & ~filters.COMMAND

    # ==========================================================================
    # 1. CONVERSATION HANDLER (مدیریت مکالمات چند مرحله‌ای)
    # ==========================================================================
    conv_handler = ConversationHandler(
        allow_reentry=True,
        entry_points=[
            # --- Admin Panel Actions ---
            CallbackQueryHandler(admin_panel.add_new_user_start, pattern='^add_new_admin$'),
            CallbackQueryHandler(admin_panel.admin_user_actions, pattern='^admin_u_limit_'),
            CallbackQueryHandler(admin_panel.admin_user_actions, pattern='^admin_u_settime_'),
            CallbackQueryHandler(admin_panel.admin_search_start, pattern='^admin_search_start$'),
            CallbackQueryHandler(admin_backup_restore_start, pattern='^admin_backup_restore_start$'),
            CallbackQueryHandler(admin_panel.admin_broadcast_start, pattern='^admin_broadcast_start$'),
            CallbackQueryHandler(admin_panel.admin_user_servers_report, pattern='^admin_u_servers_'),
            CallbackQueryHandler(admin_panel.admin_search_servers_by_uid_start, pattern='^admin_search_servers_by_uid_start$'),
            CallbackQueryHandler(admin_server_detail_action, pattern='^admin_detail_'),
            CallbackQueryHandler(admin_panel.admin_full_report_global_action, pattern='^admin_full_report_global$'),
            # --- Payment Management (Admin) ---
            CallbackQueryHandler(admin_payment_settings, pattern='^admin_pay_settings$'),
            CallbackQueryHandler(add_pay_method_start, pattern='^add_pay_method_'),
            CallbackQueryHandler(ask_for_receipt, pattern='^confirm_pay_'),

            # --- Group & Server Management ---
            CallbackQueryHandler(add_group_start, pattern='^add_group$'),
            CallbackQueryHandler(add_server_start_menu, pattern='^add_server$'),

            # --- Tools & Settings ---
            CallbackQueryHandler(manual_ping_start, pattern='^manual_ping_start$'),
            CallbackQueryHandler(add_channel_start, pattern='^add_channel$'),
            CallbackQueryHandler(ask_custom_interval, pattern='^setcron_custom$'),
            CallbackQueryHandler(edit_expiry_start, pattern='^act_editexpiry_'),
            CallbackQueryHandler(ask_terminal_command, pattern='^cmd_terminal_'),

            # --- Resource Limits ---
            CallbackQueryHandler(resource_settings_menu, pattern='^settings_thresholds$'),
            CallbackQueryHandler(ask_cpu_limit, pattern='^set_cpu_limit$'),
            CallbackQueryHandler(ask_ram_limit, pattern='^set_ram_limit$'),
            CallbackQueryHandler(ask_disk_limit, pattern='^set_disk_limit$'),

            # --- User & Reports ---
            CallbackQueryHandler(user_profile_menu, pattern='^user_profile$'),
            CallbackQueryHandler(web_token_action, pattern='^gen_web_token$'),
            CallbackQueryHandler(send_general_report_action, pattern='^act_global_full_report$'),

            # --- Auto Reboot ---
            CallbackQueryHandler(ask_reboot_time, pattern='^start_set_reboot$'),
            CallbackQueryHandler(auto_reboot_menu, pattern='^auto_reboot_menu$'),
            CallbackQueryHandler(save_auto_reboot_final, pattern='^disable_reboot$'),
            CallbackQueryHandler(save_auto_reboot_final, pattern='^savereb_'),
            CallbackQueryHandler(dashboard_sort_menu, pattern='^dashboard_sort_menu$'),
            CallbackQueryHandler(set_dashboard_sort_action, pattern='^set_dash_sort_'),
            CallbackQueryHandler(admin_panel.admin_all_servers_report, pattern='^admin_all_servers_'),

            # --- Tunnel Monitoring (Iran Node) ---
            CallbackQueryHandler(monitor_settings_panel, pattern='^monitor_settings_panel$'),
            CallbackQueryHandler(set_iran_monitor_start, pattern='^set_iran_monitor_server$'),
            CallbackQueryHandler(delete_monitor_node, pattern='^delete_monitor_node$'),
            CallbackQueryHandler(update_monitor_node, pattern='^update_monitor_node$'),

            # --- Tunnel Config Management (New Flow) ---
            CallbackQueryHandler(add_config_start, pattern='^add_tunnel_config$'),
            CallbackQueryHandler(mode_ask_json, pattern='^mode_add_json$'),
            CallbackQueryHandler(mode_ask_sub, pattern='^mode_add_sub$'),
            CallbackQueryHandler(config_stats_dashboard, pattern='^show_config_stats$'),
            
            # --- Tunnel List Actions ---
            CallbackQueryHandler(tunnel_list_menu, pattern='^tunnel_list_menu$'),
            CallbackQueryHandler(test_single_config, pattern='^test_conf_'),
            CallbackQueryHandler(view_config_action, pattern='^view_conf_'),
            CallbackQueryHandler(delete_config_action, pattern='^del_conf_'),
            
            # --- Config Detail Handlers (New) ---
            CallbackQueryHandler(show_config_details, pattern='^conf_detail_'),
            CallbackQueryHandler(copy_config_action, pattern='^copy_conf_'),
            CallbackQueryHandler(qr_config_action, pattern='^qr_conf_'),
            CallbackQueryHandler(manage_single_sub_menu, pattern='^manage_sub_'),
            CallbackQueryHandler(get_sub_links_action, pattern='^get_sub_links_'), # ✅ اضافه شد
            
            # ... بقیه هندلرها ...
            CallbackQueryHandler(topics.setup_group_notify_start, pattern='^setup_group_notify$'),
            CallbackQueryHandler(topics.get_group_id_step, pattern='^get_group_id_step$'),
            CallbackQueryHandler(config_cron_menu, pattern='^settings_conf_cron$'),
            CallbackQueryHandler(set_config_cron_action, pattern='^setconfcron_'),
            # ... در لیست CallbackQueryHandler ها ...
            CallbackQueryHandler(toggle_config_alert, pattern='^toggle_confalert_'),
            CallbackQueryHandler(header_none_action, pattern='^header_none$'),
            # --- Placeholders ---
            CallbackQueryHandler(lambda u, c: u.callback_query.answer("🔜 به‌زودی!", show_alert=True), pattern='^dev_feature$')
        ],
        states={
            SELECT_CONFIG_TYPE: [
                CallbackQueryHandler(handle_config_type_selection, pattern='^type_'),
                CallbackQueryHandler(cancel_handler_func, pattern='^cancel_flow$'),
            ],
            GET_LINEAR_DATA: [MessageHandler(text_filter, process_linear_data)],
            topics.GET_GROUP_ID_FOR_TOPICS: [MessageHandler(filters.TEXT & ~filters.COMMAND, topics.perform_group_setup)],
            # --- Advanced Monitor Settings States ---
            GET_CUSTOM_SMALL_SIZE: [MessageHandler(filters.TEXT, custom_small_handler)],
            GET_CUSTOM_BIG_SIZE: [MessageHandler(filters.TEXT, custom_big_handler)],
            GET_CUSTOM_BIG_INTERVAL: [MessageHandler(filters.TEXT, custom_int_handler)],
            # --- Admin States ---
            ADD_ADMIN_ID: [MessageHandler(text_filter, admin_panel.get_new_user_id)],
            ADD_ADMIN_DAYS: [MessageHandler(text_filter, admin_panel.get_new_user_days)],
            ADMIN_SET_LIMIT: [MessageHandler(text_filter, admin_panel.admin_set_limit_handler)],
            ADMIN_SET_TIME_MANUAL: [MessageHandler(text_filter, admin_panel.admin_set_days_handler)],
            ADMIN_SEARCH_USER: [MessageHandler(text_filter, admin_panel.admin_search_handler)],
            ADMIN_RESTORE_DB: [MessageHandler(filters.Document.ALL, admin_backup_restore_handler)], # در bot.py ماند
            GET_BROADCAST_MSG: [MessageHandler(filters.ALL & ~filters.COMMAND, admin_panel.admin_broadcast_send)],
            # --- New Admin Report State ---
            ADMIN_GET_UID_FOR_REPORT: [MessageHandler(filters.TEXT, admin_panel.admin_report_by_uid_handler)],
            # --- Payment Add States ---
            ADD_PAY_NET: [MessageHandler(text_filter, get_pay_network)],
            ADD_PAY_ADDR: [MessageHandler(text_filter, get_pay_address)],
            ADD_PAY_HOLDER: [MessageHandler(text_filter, get_pay_holder)],

            # --- General Server States ---
            GET_GROUP_NAME: [MessageHandler(text_filter, get_group_name)],
            GET_NAME: [MessageHandler(text_filter, get_srv_name)],
            GET_IP: [MessageHandler(text_filter, get_srv_ip)],
            GET_PORT: [MessageHandler(text_filter, get_srv_port)],
            GET_USER: [MessageHandler(text_filter, get_srv_user)],
            GET_PASS: [MessageHandler(text_filter, get_srv_pass)],
            GET_EXPIRY: [MessageHandler(text_filter, get_srv_expiry)],
            SELECT_GROUP: [CallbackQueryHandler(select_group)],

            # --- Tools States ---
            GET_MANUAL_HOST: [MessageHandler(text_filter, perform_manual_ping)],
            GET_CHANNEL_FORWARD: [MessageHandler(filters.ALL & ~filters.COMMAND, get_channel_forward)],
            GET_CUSTOM_INTERVAL: [MessageHandler(text_filter, set_custom_interval_action)],
            GET_CHANNEL_TYPE: [CallbackQueryHandler(set_channel_type_action, pattern='^type_')],
            EDIT_SERVER_EXPIRY: [MessageHandler(text_filter, edit_expiry_save)],
            GET_REMOTE_COMMAND: [
                MessageHandler(text_filter, run_terminal_action),
                CallbackQueryHandler(close_terminal_session, pattern='^exit_terminal$')
            ],

            # --- Resource Limit States ---
            GET_CPU_LIMIT: [MessageHandler(text_filter, save_cpu_limit)],
            GET_RAM_LIMIT: [MessageHandler(text_filter, save_ram_limit)],
            GET_DISK_LIMIT: [MessageHandler(text_filter, save_disk_limit)],

            # --- Auto Reboot State ---
            GET_REBOOT_TIME: [MessageHandler(text_filter, receive_reboot_time_and_show_freq)],
            GET_RECEIPT: [
                MessageHandler(filters.PHOTO | filters.Document.IMAGE, process_receipt_upload)
            ],
            # --- Iran Server States ---
            GET_IRAN_NAME: [
                MessageHandler(text_filter, get_iran_name),
                CallbackQueryHandler(cancel_handler_func, pattern='^cancel_flow$')
            ],
            GET_IRAN_IP: [
                MessageHandler(text_filter, get_iran_ip),
                CallbackQueryHandler(cancel_handler_func, pattern='^cancel_flow$')
            ],
            GET_IRAN_PORT: [
                MessageHandler(text_filter, get_iran_port),
                CallbackQueryHandler(cancel_handler_func, pattern='^cancel_flow$')
            ],
            GET_IRAN_USER: [
                MessageHandler(text_filter, get_iran_user),
                CallbackQueryHandler(cancel_handler_func, pattern='^cancel_flow$')
            ],
            GET_IRAN_PASS: [
                MessageHandler(text_filter, get_iran_pass),
                CallbackQueryHandler(cancel_handler_func, pattern='^cancel_flow$')
            ],
            # --- Config States ---
            GET_JSON_CONF: [MessageHandler(filters.TEXT | filters.Document.ALL, process_json_config)],
            GET_SUB_LINK: [MessageHandler(filters.TEXT, process_sub_link)],
            GET_CONFIG_LINKS: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_add_config)],
            GET_SUB_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, finalize_sub_adding)],
        },
        fallbacks=[
            CommandHandler('cancel', cancel_handler_func),
            CallbackQueryHandler(cancel_handler_func, pattern='^cancel_flow$'),
            CommandHandler('start', start)
        ]
    )
    app.add_handler(conv_handler)

    # ==========================================================================
    # 2. SECRET KEY MANAGEMENT
    # ==========================================================================
    key_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_key_restore_start, pattern='^admin_key_restore_start$')],
        states={
            ADMIN_RESTORE_KEY: [MessageHandler(filters.Document.ALL, admin_key_restore_handler)]
        },
        fallbacks=[CallbackQueryHandler(cancel_handler_func, pattern='^cancel_flow$')]
    )
    app.add_handler(key_conv_handler)
    app.add_handler(CallbackQueryHandler(admin_key_backup_get, pattern='^admin_key_backup_get$'))

    # ==========================================================================
    # 3. COMMAND HANDLERS
    # ==========================================================================
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('dashboard', dashboard_command))
    app.add_handler(CommandHandler('setting', settings_command))

    # ==========================================================================
    # 4. CALLBACK HANDLERS
    # ==========================================================================

    # --- Main Menu & Basics ---
    app.add_handler(CallbackQueryHandler(main_menu, pattern='^main_menu$'))
    app.add_handler(CallbackQueryHandler(status_dashboard, pattern='^status_dashboard$'))
    app.add_handler(CallbackQueryHandler(dashboard_sort_menu, pattern='^dashboard_sort_menu$'))
    app.add_handler(CallbackQueryHandler(set_dashboard_sort_action, pattern='^set_dash_sort_'))
    # در قسمت CallbackQueryHandlers اضافه کنید:
    app.add_handler(CallbackQueryHandler(delete_item_from_list_action, pattern='^del_list_item_'))
    # --- Admin Panel ---
    app.add_handler(CallbackQueryHandler(admin_panel.admin_panel_main, pattern='^admin_panel_main$'))
    app.add_handler(CallbackQueryHandler(admin_panel.admin_users_list, pattern='^admin_users_page_'))
    app.add_handler(CallbackQueryHandler(admin_panel.admin_user_manage, pattern='^admin_u_manage_'))
    app.add_handler(CallbackQueryHandler(admin_panel.admin_user_actions, pattern='^admin_u_'))
    app.add_handler(CallbackQueryHandler(admin_panel.admin_users_text, pattern='^admin_users_text$'))
    app.add_handler(CallbackQueryHandler(admin_backup_get, pattern='^admin_backup_get$')) # در bot.py ماند
    
    # --- Admin Reports ---
    app.add_handler(CallbackQueryHandler(admin_panel.admin_all_servers_report, pattern='^admin_all_servers_'))
    # --- Server & Group Actions ---
    app.add_handler(CallbackQueryHandler(groups_menu, pattern='^groups_menu$'))
    app.add_handler(CallbackQueryHandler(delete_group_action, pattern='^delgroup_'))
    app.add_handler(CallbackQueryHandler(list_groups_for_servers, pattern='^list_groups_for_servers$'))
    app.add_handler(CallbackQueryHandler(show_servers, pattern='^(listsrv_|list_all)'))
    app.add_handler(CallbackQueryHandler(server_detail, pattern='^detail_'))
    app.add_handler(CallbackQueryHandler(server_actions, pattern='^act_'))
    app.add_handler(CallbackQueryHandler(manage_servers_list, pattern='^manage_servers_list$'))
    app.add_handler(CallbackQueryHandler(toggle_server_active_action, pattern='^toggle_active_'))
    app.add_handler(CallbackQueryHandler(show_server_stats, pattern='^show_server_stats$'))

    # --- Tunnel Configuration ---
    app.add_handler(CallbackQueryHandler(tunnel_list_menu, pattern='^tunnel_list_menu$'))
    app.add_handler(CallbackQueryHandler(mass_update_test_start, pattern='^mass_update_test_all$'))
    app.add_handler(CallbackQueryHandler(show_tunnels_by_mode, pattern='^list_mode_'))
    app.add_handler(CallbackQueryHandler(update_all_configs_status, pattern='^update_all_tunnels$'))
    app.add_handler(CallbackQueryHandler(test_single_config, pattern='^test_conf_'))
    app.add_handler(CallbackQueryHandler(view_config_action, pattern='^view_conf_'))
    app.add_handler(CallbackQueryHandler(delete_config_action, pattern='^del_conf_'))
    app.add_handler(CallbackQueryHandler(manage_single_sub_menu, pattern='^manage_sub_'))
    app.add_handler(CallbackQueryHandler(manual_update_sub_action, pattern='^update_sub_'))
    app.add_handler(CallbackQueryHandler(delete_full_subscription, pattern='^del_sub_full_'))
    
    # --- New Config Detail Buttons ---
    app.add_handler(CallbackQueryHandler(show_config_details, pattern='^conf_detail_'))
    app.add_handler(CallbackQueryHandler(copy_config_action, pattern='^copy_conf_'))
    app.add_handler(CallbackQueryHandler(qr_config_action, pattern='^qr_conf_'))
    app.add_handler(CallbackQueryHandler(get_sub_links_action, pattern='^get_sub_links_'))

    # --- Tunnel Monitoring (Iran Node) ---
    app.add_handler(CallbackQueryHandler(monitor_settings_panel, pattern='^monitor_settings_panel$'))
    app.add_handler(CallbackQueryHandler(delete_monitor_node, pattern='^delete_monitor_node$'))
    app.add_handler(CallbackQueryHandler(update_monitor_node, pattern='^update_monitor_node$'))

    # --- Wallet, Payment & Referral ---
    app.add_handler(CallbackQueryHandler(wallet_menu, pattern='^wallet_menu$'))
    app.add_handler(CallbackQueryHandler(referral_menu, pattern='^referral_menu$'))
    app.add_handler(CallbackQueryHandler(select_payment_method, pattern='^buy_plan_'))
    app.add_handler(CallbackQueryHandler(show_payment_details, pattern='^pay_method_'))
    app.add_handler(CallbackQueryHandler(delete_payment_method_action, pattern='^del_pay_method_'))
    app.add_handler(CallbackQueryHandler(admin_approve_payment_action, pattern='^admin_approve_pay_'))
    app.add_handler(CallbackQueryHandler(admin_reject_payment_action, pattern='^admin_reject_pay_'))

    # --- Global Operations ---
    app.add_handler(CallbackQueryHandler(global_ops_menu, pattern='^global_ops_menu$'))
    app.add_handler(CallbackQueryHandler(global_action_handler, pattern='^glob_act_'))

    # --- Settings & Utilities ---
    app.add_handler(CallbackQueryHandler(settings_menu, pattern='^settings_menu$'))
    app.add_handler(CallbackQueryHandler(set_dns_action, pattern='^setdns_'))
    app.add_handler(CallbackQueryHandler(channels_menu, pattern='^channels_menu$'))
    app.add_handler(CallbackQueryHandler(delete_channel_action, pattern='^delchan_'))
    app.add_handler(CallbackQueryHandler(schedules_settings_menu, pattern='^menu_schedules$'))
    app.add_handler(CallbackQueryHandler(settings_cron_menu, pattern='^settings_cron$'))
    app.add_handler(CallbackQueryHandler(set_cron_action, pattern='^setcron_'))
    app.add_handler(CallbackQueryHandler(toggle_down_alert, pattern='^toggle_downalert_'))
    app.add_handler(CallbackQueryHandler(send_general_report_action, pattern='^send_general_report$'))

    # --- Advanced Monitoring Settings ---
    app.add_handler(CallbackQueryHandler(advanced_monitoring_settings, pattern='^advanced_monitoring_settings$'))
    app.add_handler(CallbackQueryHandler(set_small_size_menu, pattern='^set_small_size_menu$'))
    app.add_handler(CallbackQueryHandler(set_big_size_menu, pattern='^set_big_size_menu$'))
    app.add_handler(CallbackQueryHandler(set_big_interval_menu, pattern='^set_big_interval_menu$'))
    app.add_handler(CallbackQueryHandler(save_setting_action, pattern='^save_'))

    # --- Auto Schedule Settings ---
    app.add_handler(CallbackQueryHandler(auto_update_menu, pattern='^auto_up_menu$'))
    app.add_handler(CallbackQueryHandler(save_auto_schedule, pattern='^set_autoup_'))
    app.add_handler(CallbackQueryHandler(save_auto_reboot_final, pattern='^(savereb_|disable_reboot)'))
    app.add_handler(CallbackQueryHandler(show_add_service_menu, pattern='^open_add_menu$'))
    app.add_handler(CallbackQueryHandler(show_lists_menu, pattern='^open_lists_menu$'))
    app.add_handler(CallbackQueryHandler(show_account_menu, pattern='^open_account_menu$'))
    app.add_handler(CallbackQueryHandler(refresh_conf_dash_action, pattern='^refresh_conf_dash_ping$'))
# ==========================================================================
    # 5. JOB QUEUE (وظایف زمان‌بندی شده از ماژول cronjobs)
    # ==========================================================================
    if app.job_queue:
        # --- Startup ---
        # (خطوط تکراری حذف شدند تا پیام دوبله نیاید)
        app.job_queue.run_once(cronjobs.system_startup_notification, when=2)
        app.job_queue.run_once(cronjobs.startup_whitelist_job, when=15)
        app.job_queue.run_once(cronjobs.send_startup_topic_test, when=10)
        
        # --- Daily ---
        app.job_queue.run_daily(cronjobs.check_expiry_job, time=dt.time(hour=8, minute=30, second=0))

        # --- Recurring ---
        app.job_queue.run_repeating(cronjobs.auto_scheduler_job, interval=120, first=30)
        
        # مانیتورینگ سرورها: هر ۶۰ ثانیه (۱ دقیقه)
        app.job_queue.run_repeating(cronjobs.global_monitor_job, interval=60, first=10)
        
        # مانیتورینگ کانفیگ‌ها: هر ۶۰ ثانیه (۱ دقیقه)
        app.job_queue.run_repeating(cronjobs.monitor_tunnels_job, interval=60, first=20)
        
        # آپدیت ساب‌ها: هر ۱۲ ساعت
        app.job_queue.run_repeating(cronjobs.auto_update_subs_job, interval=43200, first=3600)

        app.job_queue.run_repeating(cronjobs.auto_backup_send_job, interval=3600, first=300)
        app.job_queue.run_repeating(cronjobs.check_bonus_expiry_job, interval=43200, first=600)

    else:
        logger.error("JobQueue not available.")

    # اجرا
    app.run_polling(drop_pending_updates=True, close_loop=False)


if __name__ == '__main__':
    main()