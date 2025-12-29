import logging
import asyncio
import os
import json
from datetime import datetime, timedelta
import jdatetime

# --- Telegram Imports ---
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

# --- Local Modules ---
import keyboard
from states import *
from database import Database
from settings import SUPER_ADMIN_ID, KEY_FILE
from core import ServerMonitor, get_jalali_str, get_tehran_datetime, sec
from server_stats import StatsManager
# ایمپورت موتور امتیازدهی
from scoring import ScoreEngine
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)
db = Database()
async def safe_edit_message(update: Update, text, reply_markup=None, parse_mode='Markdown'):
    try:
        if update.callback_query:
            return await update.callback_query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
        elif update.message:
            return await update.message.reply_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception:
        pass
    return None

# ==============================================================================
# 👑 ADMIN PANEL HANDLERS
# ==============================================================================

async def admin_panel_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != SUPER_ADMIN_ID: return
    users_count = len(db.get_all_users())
    
    # 👇 اصلاح شد: باز کردن صحیح کانکشن و نشانگر
    with db.get_connection() as (conn, cur):
        cur.execute('SELECT id FROM servers')
        total_servers = len(cur.fetchall())

    reply_markup = keyboard.admin_main_kb()
    txt = (
        f"🤖 **پنل مدیریت ربات**\n\n"
        f"📊 **آمار کلی:**\n"
        f"👤 کل کاربران: `{users_count}`\n"
        f"🖥 کل سرورهای ثبت شده: `{total_servers}`"
    )
    await safe_edit_message(update, txt, reply_markup=reply_markup)

async def admin_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    page = int(update.callback_query.data.split('_')[-1])
    users, total_count = db.get_all_users_paginated(page, 5)
    total_pages = (total_count + 4) // 5

    txt = f"👥 **لیست کاربران (صفحه {page} از {total_pages})**\nتعداد کل: `{total_count}`\n➖➖➖➖➖➖"
    reply_markup = keyboard.admin_users_list_kb(users, page, total_pages)
    await safe_edit_message(update, txt, reply_markup=reply_markup)

async def admin_user_manage(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id=None):
    if not user_id and update.callback_query:
        data = update.callback_query.data
        if "manage_" in data:
            try: user_id = int(data.split('_')[-1])
            except: pass

    if not user_id:
        await safe_edit_message(update, "❌ خطای سیستمی: آیدی کاربر پیدا نشد.")
        return

    user = db.get_user(user_id)
    if not user:
        await safe_edit_message(update, "❌ کاربر در دیتابیس یافت نشد.")
        return

    plan_txt = "💎 پریمیوم (VIP)" if user['plan_type'] == 1 else "👤 عادی (Normal)"
    ban_status = "🔴 مسدود" if user['is_banned'] else "🟢 فعال"

    txt = (
        f"👤 **مدیریت کاربر:** `{user['full_name']}`\n"
        f"🆔 آیدی: `{user['user_id']}`\n"
        f"💳 **نوع اشتراک:** {plan_txt}\n"
        f"📆 انقضا: `{user['expiry_date']}`\n"
        f"📡 وضعیت: {ban_status}\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"📊 سرورها: `{len(db.get_all_user_servers(user_id))}` / `{user['server_limit']}`"
    )
    reply_markup = keyboard.admin_user_manage_kb(user_id, user['plan_type'], user['is_banned'])
    await safe_edit_message(update, txt, reply_markup=reply_markup)

async def admin_user_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data
    action = data.split('_')[2]
    target_id = int(data.split('_')[3])

    if action == 'ban':
        new_state = db.toggle_ban_user(target_id)
        msg = "کاربر مسدود شد." if new_state else "کاربر فعال شد."
        try: await update.callback_query.answer(msg)
        except: pass
        await admin_user_manage(update, context, user_id=target_id)

    elif action == 'del':
        db.remove_user(target_id)
        try: await update.callback_query.answer("کاربر حذف شد.")
        except: pass
        await admin_users_list(update, context)

    elif action == 'addtime':
        db.add_or_update_user(target_id, days=30)
        try: await update.callback_query.answer("30 روز تمدید شد.")
        except: pass
        await admin_user_manage(update, context, user_id=target_id)

    elif action == 'limit':
        context.user_data['target_uid'] = target_id
        await safe_edit_message(update, "🔢 **تعداد جدید محدودیت سرور را وارد کنید:**", reply_markup=keyboard.get_cancel_markup())
        return ADMIN_SET_LIMIT

    elif action == 'settime':
        context.user_data['target_uid'] = target_id
        await safe_edit_message(update, "📅 **تعداد روز اعتبار را وارد کنید (مثلا 60):**", reply_markup=keyboard.get_cancel_markup())
        return ADMIN_SET_TIME_MANUAL

    elif action == 'toggleplan':
        new_plan = db.toggle_user_plan(target_id)
        msg = "✅ کاربر به پریمیوم ارتقا یافت" if new_plan == 1 else "⬇️ کاربر به عادی تغییر یافت"
        try: await update.callback_query.answer(msg, show_alert=True)
        except: pass
        await admin_user_manage(update, context, user_id=target_id)

async def admin_set_limit_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        lim = int(update.message.text)
        target_id = context.user_data.get('target_uid')
        db.update_user_limit(target_id, lim)
        await update.message.reply_text(f"✅ محدودیت سرور به {lim} تغییر یافت.")
        await admin_user_manage(update, context, user_id=target_id)
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ لطفاً فقط عدد انگلیسی وارد کنید.")
        return ADMIN_SET_LIMIT

async def admin_set_days_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        days = int(update.message.text)
        target_id = context.user_data.get('target_uid')
        db.add_or_update_user(target_id, days=days)
        await update.message.reply_text(f"✅ اعتبار کاربر {days} روز تمدید شد.")
        await admin_user_manage(update, context, user_id=target_id)
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ لطفاً فقط عدد انگلیسی وارد کنید.")
        return ADMIN_SET_TIME_MANUAL

async def admin_search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_edit_message(update, "🔎 **آیدی عددی کاربر را ارسال کنید:**", reply_markup=keyboard.get_cancel_markup())
    return ADMIN_SEARCH_USER

async def admin_search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        tid = int(update.message.text)
        user = db.get_user(tid)
        if user:
            await admin_user_manage(update, context, user_id=tid)
            return ConversationHandler.END
        else:
            await update.message.reply_text("❌ کاربر یافت نشد.")
            return ADMIN_SEARCH_USER
    except:
        await update.message.reply_text("❌ فرمت نامعتبر.")
        return ADMIN_SEARCH_USER

async def admin_users_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = db.get_all_users()
    txt = "📋 **لیست کل کاربران:**\n\n"
    for u in users:
        txt += f"🆔 {u['user_id']} | 👤 {u['full_name']} | 📅 Exp: {u['expiry_date']}\n"

    if len(txt) > 4000:
        with open("users_list.txt", "w", encoding='utf-8') as f: f.write(txt)
        try: await update.callback_query.message.reply_document(document=open("users_list.txt", "rb"), caption="لیست کاربران")
        except: pass
        os.remove("users_list.txt")
    else:
        await update.callback_query.message.reply_text(txt)

# --- Broadcast ---
async def admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_edit_message(update, "📢 **لطفاً پیام خود را ارسال کنید:**\n\nبرای تمام کاربران ارسال می‌شود.", reply_markup=keyboard.get_cancel_markup())
    return GET_BROADCAST_MSG

async def admin_broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = db.get_all_users()
    total = len(users)
    success = 0
    blocked = 0
    status_msg = await update.message.reply_text(f"⏳ در حال ارسال به {total} کاربر...")

    for user in users:
        try:
            await update.message.copy(chat_id=user['user_id'])
            success += 1
        except: blocked += 1
        if success % 20 == 0: await asyncio.sleep(1)

    await status_msg.edit_text(f"✅ **ارسال شد.**\n👥 کل: `{total}`\n✅ موفق: `{success}`\n🚫 ناموفق: `{blocked}`")
    await admin_panel_main(update, context)
    return ConversationHandler.END

# --- Add New User ---
async def add_new_user_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: await update.callback_query.answer()
    except: pass
    await safe_edit_message(update, "👤 **شناسه عددی (User ID) کاربر را وارد کنید:**", reply_markup=keyboard.get_cancel_markup())
    return ADD_ADMIN_ID

async def get_new_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['new_uid'] = int(update.message.text)
        await update.message.reply_text("📅 **تعداد روز اعتبار:**", reply_markup=keyboard.get_cancel_markup())
        return ADD_ADMIN_DAYS
    except:
        await update.message.reply_text("❌ فقط عدد وارد کنید.")
        return ADD_ADMIN_ID

async def get_new_user_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        db.add_or_update_user(context.user_data['new_uid'], full_name="User (Manual)", days=int(update.message.text))
        await update.message.reply_text("✅ کاربر افزوده شد.")
        await admin_panel_main(update, context) # بازگشت به پنل ادمین
        return ConversationHandler.END
    except:
        await update.message.reply_text("❌ فقط عدد وارد کنید.")
        return ADD_ADMIN_DAYS

# --- Global Server Reports ---
async def admin_all_servers_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != SUPER_ADMIN_ID: return
    query = update.callback_query
    try: page = int(query.data.split('_')[-1])
    except: page = 1
    
    ITEMS_PER_PAGE = 3 
    all_users = db.get_all_users()
    users_with_active_servers = []
    for u in all_users:
        servers = db.get_all_user_servers(u['user_id'])
        if any(s['is_active'] == 1 for s in servers):
            users_with_active_servers.append(u)

    total = len(users_with_active_servers)
    total_pages = (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    start_idx = (page - 1) * ITEMS_PER_PAGE
    current_users = users_with_active_servers[start_idx:start_idx + ITEMS_PER_PAGE]

    txt = f"📜 **لیست کاربران دارای سرور فعال**\n📄 صفحه `{page}` از `{total_pages}`\n➖➖➖➖➖➖\n"
    for u in current_users:
        servers = db.get_all_user_servers(u['user_id'])
        active = [s for s in servers if s['is_active']]
        txt += f"👤 **{u['full_name']}** (`{u['user_id']}`)\n📦 فعال: `{len(active)}`\n"
        for i, s in enumerate(active, 1):
            status = "🟢" if s['last_status'] == 'Online' else "🔴"
            expiry = s['expiry_date'].split(' ')[0] if s['expiry_date'] else "♾"
            txt += f"   {i}. {status} **{s['name']}** | 📅 {expiry}\n"
        txt += "➖\n"

    reply_markup = keyboard.admin_global_report_kb(page, total_pages)
    await safe_edit_message(update, txt, reply_markup=reply_markup)

async def admin_full_report_global_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("⏳ شروع گزارش جامع...")
    await update.callback_query.message.reply_text("⚠️ **شروع آنالیز تمام سرورها...**\nلطفاً صبور باشید.")
    asyncio.create_task(run_full_global_report(context, update.effective_chat.id))

async def run_full_global_report(context, chat_id):
    loop = asyncio.get_running_loop()
    all_servers = await loop.run_in_executor(EXECUTOR, db.get_all_servers)
    active_servers = [s for s in all_servers if s['is_active']]

    if not active_servers:
        await context.bot.send_message(chat_id, "❌ سرور فعالی یافت نشد.")
        return
    
    sem = asyncio.Semaphore(10)
    async def safe_check(s):
        async with sem:
            return await loop.run_in_executor(EXECUTOR, StatsManager.check_full_stats, s['ip'], s['port'], s['username'], sec.decrypt(s['password']))

    results = await asyncio.gather(*[safe_check(s) for s in active_servers], return_exceptions=True)
    report_lines = []
    
    for srv, res in zip(active_servers, results):
        if isinstance(res, dict) and res.get('status') == 'Online':
            # استفاده از ScoreEngine برای ساخت نوار وضعیت
            cpu = ScoreEngine.make_bar(res['cpu'], 5)
            report_lines.append(f"🟢 **{srv['name']}**\n   🆔 User: `{srv['owner_id']}`\n   🧠 {cpu} {res['cpu']}%\n   ⏱ {res['uptime_str']}\n")
        else:
            err = res.get('error', 'Error') if isinstance(res, dict) else "Error"
            report_lines.append(f"🔴 **{srv['name']}**\n   🆔 User: `{srv['owner_id']}`\n   ❌ {err}\n")

    final_report = f"🌍 **گزارش جامع سرورها**\n📅 `{get_jalali_str()}`\n➖➖➖➖➖➖\n" + "\n".join(report_lines)
    
    if len(final_report) > 4000:
        for i in range(0, len(final_report), 4000):
            await context.bot.send_message(chat_id, final_report[i:i+4000], parse_mode='Markdown')
    else:
        await context.bot.send_message(chat_id, final_report, parse_mode='Markdown')

# --- User Search & Detail ---
async def admin_search_servers_by_uid_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_edit_message(update, "🔎 **آیدی عددی کاربر را ارسال کنید:**", reply_markup=keyboard.get_cancel_markup())
    return ADMIN_GET_UID_FOR_REPORT

async def admin_report_by_uid_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        target_uid = int(update.message.text)
        servers = db.get_all_user_servers(target_uid)
        if not servers:
            await update.message.reply_text("⚠️ این کاربر سروری ندارد.")
            return ConversationHandler.END
        
        txt = f"🖥 **سرورهای کاربر:** `{target_uid}`\n➖➖➖➖➖➖\n"
        kb = []
        for s in servers:
            icon = "🟢" if s['is_active'] else "🔴"
            kb.append([InlineKeyboardButton(f"{icon} {s['name']}", callback_data=f'admin_detail_{s["id"]}')])
        kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data='admin_panel_main')])
        
        await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb))
        return ConversationHandler.END
    except:
        await update.message.reply_text("❌ آیدی نامعتبر.")
        return ADMIN_GET_UID_FOR_REPORT

async def admin_server_detail_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # این تابع صرفاً برای هماهنگی کالبک‌هاست، لاجیک اصلی در server_detail است
    # اما چون server_detail در bot.py است، اینجا فقط یک پیام موقت میدهیم
    # یا می‌توانیم آن را ایمپورت کنیم (ولی باعث چرخه می‌شود).
    # راه حل: در bot.py هندلر این کالبک را به server_detail متصل نگه می‌داریم.
    pass 

async def admin_user_servers_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    target_uid = int(query.data.split('_')[3])
    servers = db.get_all_user_servers(target_uid)
    
    if not servers:
        await query.answer("❌ سروری ندارد.", show_alert=True)
        return

    txt = f"👤 **گزارش سرورهای کاربر {target_uid}**\n\n"
    for s in servers:
        txt += f"🔹 **{s['name']}**\n   🌐 {s['ip']}\n   📡 {s['last_status']}\n\n"
    
    kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data=f'admin_u_manage_{target_uid}')]]
    await safe_edit_message(update, txt, reply_markup=InlineKeyboardMarkup(kb))