from rs_shared import *

# ==============================================================================
# 🚀 STARTUP & MENU HANDLERS
# ==============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in USER_ACTIVE_TASKS:
        task = USER_ACTIVE_TASKS[user_id]
        if not task.done():
            task.cancel()
            try: 
                await task
            except asyncio.CancelledError: 
                pass
        USER_ACTIVE_TASKS.pop(user_id, None)
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
    existing_user = await loop.run_in_executor(EXECUTOR, db.get_user, user_id)
    is_new_user = False if existing_user else True
    if is_new_user and user_id != SUPER_ADMIN_ID and args and args[0].isdigit():
        possible_inviter = int(args[0])
        if possible_inviter != user_id:
            inviter_exists = await loop.run_in_executor(EXECUTOR, db.get_user, possible_inviter)
            if inviter_exists:
                inviter_id = possible_inviter
    await loop.run_in_executor(EXECUTOR, db.add_or_update_user, user_id, full_name, inviter_id)

    if user_id == SUPER_ADMIN_ID: return

    if is_new_user:
        try:
            admin_msg = f"🔔 **کاربر جدید!**\n👤 {full_name}\n🆔 `{user_id}`\n🔗 دعوت: `{inviter_id if inviter_id else 'مستقیم'}`"
            await context.bot.send_message(chat_id=SUPER_ADMIN_ID, text=admin_msg, parse_mode='Markdown')
        except: pass

        if inviter_id != 0:
            ok, new_lim, new_exp = await loop.run_in_executor(EXECUTOR, db.apply_referral_reward, inviter_id)
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
    
    has_access, msg = await loop.run_in_executor(EXECUTOR, db.check_access, user_id)
    if not has_access:
        msg_text = f"⛔️ دسترسی مسدود است: {msg}"
        if update.callback_query: await safe_edit_message(update, msg_text)
        else: await update.message.reply_text(msg_text)
        return

    remaining = f"{msg} روز" if isinstance(msg, int) else "♾ نامحدود"
    is_monitor_ready = await loop.run_in_executor(EXECUTOR, db.is_monitor_active)
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


