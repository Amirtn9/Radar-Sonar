from rs_shared import *
from rs_tunnels import wallet_menu

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
