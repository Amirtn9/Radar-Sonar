from rs_shared import *

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
    await safe_edit_message(
        update,
        "⚠️ **هشدار:** با آپلود فایل جدید، دیتابیس فعلی بازنویسی می‌شود.\n\n📂 **فایل بکاپ `.sql` را ارسال کنید:**",
        reply_markup=keyboard.get_cancel_markup()
    )
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
        cur.execute("SELECT * FROM servers WHERE is_monitor_node=1") # 👈 اجرا در یک خط
        monitor = cur.fetchone() # 👈 دریافت نتیجه در خط بعد

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
    
    # تسک واقعی در پس‌زمینه
    task = loop.run_in_executor(EXECUTOR, install_process_sync)
    
    # حلقه نمایش وضعیت فیک
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
            # 🟢 اصلاح شده: باز کردن صحیح کانکشن و کرسر
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

    success, result = await loop.run_in_executor(EXECUTOR, update_process)

    if success:
        await msg.edit_text(
            "✅ **بروزرسانی موفقیت‌آمیز بود.**\n\n"
            "🔹 فایل `monitor_agent.py` جایگزین شد.\n"
            "🔹 دسترسی فایل لاگ بررسی شد.\n"
            "🔹 سیستم آماده کار است."
        )
    else:
        await msg.edit_text(f"❌ **خطا در بروزرسانی:**\n`{result}`")



# ------------------ Admin: Logs & Services (Bat Theme) ------------------

def _admin_only(uid: int) -> bool:
    try:
        return int(uid) == int(SUPER_ADMIN_ID)
    except Exception:
        return False

def _run_shell(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=20)
        return (r.stdout or "").strip()
    except Exception as e:
        return f"ERROR: {e}"

def _format_pre(text: str, limit: int = 3500) -> str:
    if not text:
        text = "(empty)"
    if len(text) > limit:
        text = text[-limit:]
        text = "…(truncated)\n" + text
    # Use HTML <pre> to keep monospaced logs
    return f"<pre>{html.escape(text)}</pre>"

async def admin_logs_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q:
        await q.answer()
        uid = q.from_user.id
    else:
        uid = update.effective_user.id

    if not _admin_only(uid):
        if q:
            await q.answer("دسترسی ندارید ⛔️", show_alert=True)
        return

    text = "🦇 <b>مدیریت لاگ‌ها</b>\n\nیکی رو انتخاب کن:"
    await safe_edit_message(update, text, reply_markup=keyboard.admin_logs_kb(), parse_mode=ParseMode.HTML)

async def admin_show_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return
    await q.answer()

    uid = q.from_user.id
    if not _admin_only(uid):
        await q.answer("دسترسی ندارید ⛔️", show_alert=True)
        return

    data = q.data or ""
    unit = None
    title = None

    if data == "admin_log_bot":
        unit = os.getenv("SONAR_SERVICE_BOT", "sonar-bot")
        title = "🦇 لاگ BOT"
    elif data == "admin_log_api":
        unit = os.getenv("SONAR_SERVICE_API", "sonar-api")
        title = "🦇 لاگ API"
    elif data == "admin_log_agent":
        unit = os.getenv("SONAR_SERVICE_AGENT", "sonar-agent")
        title = "🦇 لاگ AGENT"
    elif data == "admin_log_postgres":
        unit = os.getenv("SONAR_SERVICE_PG", "postgresql")
        title = "🦇 لاگ PostgreSQL"
    else:
        return

    out = _run_shell(["journalctl", "-u", unit, "-n", "200", "--no-pager"])
    msg = f"<b>{title}</b>\n\n" + _format_pre(out)
    await safe_edit_message(update, msg, reply_markup=keyboard.admin_logs_kb(), parse_mode=ParseMode.HTML)

async def admin_services_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q:
        await q.answer()
        uid = q.from_user.id
    else:
        uid = update.effective_user.id

    if not _admin_only(uid):
        if q:
            await q.answer("دسترسی ندارید ⛔️", show_alert=True)
        return

    text = "🦇 <b>مدیریت سرویس‌ها</b>\n\nریستارت/وضعیت سرویس‌ها:"
    await safe_edit_message(update, text, reply_markup=keyboard.admin_services_kb(), parse_mode=ParseMode.HTML)

async def admin_service_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return
    await q.answer()

    uid = q.from_user.id
    if not _admin_only(uid):
        await q.answer("دسترسی ندارید ⛔️", show_alert=True)
        return

    data = q.data or ""
    # Map callbacks to systemd units
    units = {
        "bot": os.getenv("SONAR_SERVICE_BOT", "sonar-bot"),
        "api": os.getenv("SONAR_SERVICE_API", "sonar-api"),
        "agent": os.getenv("SONAR_SERVICE_AGENT", "sonar-agent"),
    }

    def parse_action(d: str):
        # e.g. svc_restart_bot
        parts = d.split("_")
        if len(parts) != 3:
            return None, None
        _, action, target = parts
        return action, target

    action, target = parse_action(data)
    if action not in {"restart", "status"} or target not in units:
        return

    unit = units[target]

    if action == "restart":
        out = _run_shell(["systemctl", "restart", unit])
        status = _run_shell(["systemctl", "is-active", unit])
        msg = f"🦇 <b>Restart {html.escape(unit)}</b>\nوضعیت: <b>{html.escape(status)}</b>\n"
        if out:
            msg += "\n" + _format_pre(out, limit=1200)
    else:
        out = _run_shell(["systemctl", "status", unit, "--no-pager", "-n", "30"])
        msg = f"🦇 <b>Status {html.escape(unit)}</b>\n\n" + _format_pre(out)

    await safe_edit_message(update, msg, reply_markup=keyboard.admin_services_kb(), parse_mode=ParseMode.HTML)
