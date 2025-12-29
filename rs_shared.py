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
import subprocess
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

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
from states import *
import topics
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
    get_tehran_datetime, extract_safe_json, sec
)
from settings import (
    DB_NAME, CONFIG_FILE, KEY_FILE, AGENT_FILE_PATH, 
    SUBSCRIPTION_PLANS, PAYMENT_INFO, DEFAULT_INTERVAL, 
    DOWN_RETRY_LIMIT, SUPER_ADMIN_ID, DB_CONFIG, AGENT_PORT
)

# ==============================================================================
# ⚙️ CONCURRENCY SETTINGS (تنظیمات همزمانی و مدیریت فشار)
# ==============================================================================

# تعداد پردازش‌های همزمان مجاز (برای جلوگیری از کرش کردن سرور)
MAX_CONCURRENT_TASKS = 50 
# این متغیر جایگزین None در run_in_executor می‌شود
EXECUTOR = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_TASKS)

# ساخت سمافور سراسری (برای صف‌بندی درخواست‌ها وقتی ظرفیت پر است)
GLOBAL_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_TASKS)
# ==============================================================================
# 🚀 INITIALIZATION & CONFIGURATION
# ==============================================================================

logger = setup_logger()
db = Database()
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
# ==============================================================================
# 🎮 UI HELPERS & GENERAL HANDLERS
# ==============================================================================
async def safe_edit_message(update: Update, text, reply_markup=None, parse_mode='Markdown'):
    """Safely edit a callback message or reply to a message.

    Returns:
        telegram.Message | None
    """
    try:
        if update.callback_query:
            # اگر متن/کیبورد تغییر نکرده باشد، تلگرام BadRequest می‌دهد.
            return await update.callback_query.edit_message_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
        if update.message:
            return await update.message.reply_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
    except BadRequest as e:
        # اگر ارور این بود که "Message is not modified"، نادیده بگیر
        if "Message is not modified" in str(e):
            return None
        logger.error(f"Edit Error: {e}")
    except Exception as e:
        logger.error(f"General Edit Error: {e}")
    return None


async def cancel_handler_func(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        try:
            await update.callback_query.answer()
        except:
            pass
    await safe_edit_message(update, "🚫 **عملیات لغو شد.**")
    await asyncio.sleep(1)
    from rs_start import start
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
    # بررسی می‌کنیم آیا ظرفیت خالی داریم یا نه
    if GLOBAL_SEMAPHORE.locked():
        try:
            await context.bot.send_message(chat_id=chat_id, text="⚠️ **سرور شلوغ است!**\nلطفاً چند لحظه صبر کنید تا پردازش‌های فعلی تمام شوند.")
        except: pass
        return

    loop = asyncio.get_running_loop()
    
    # ورود به صف پردازش با استفاده از سمافور
    async with GLOBAL_SEMAPHORE:
        try:
            # نکته مهم: اینجا به جای None، متغیر EXECUTOR رو پاس میدیم
            ok, output = await loop.run_in_executor(EXECUTOR, func, *args)
            
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
