from rs_shared import *

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


# --- هندلرهای انتخاب حالت (Mode) ---

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


# --- پردازش فایل یا متن JSON ---

async def process_json_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    config_content = ""

    # ۱. دریافت محتوا (متن یا فایل)
    if update.message.document:
        f = await update.message.document.get_file()
        byte_arr = await f.download_as_bytearray()
        config_content = byte_arr.decode('utf-8')
    elif update.message.text:
        config_content = update.message.text
    else:
        await update.message.reply_text("❌ لطفاً فقط متن یا فایل ارسال کنید.")
        return GET_JSON_CONF

    # ۲. اعتبارسنجی JSON
    try:
        data = json.loads(config_content)
        # اگر جیسون معتبر بود، اسمش را از تگ برمی‌داریم
        name = data.get('tag', f"JSON_{int(time.time())}")

        # ذخیره در دیتابیس (کانفیگ را فشرده می‌کنیم)
        minified_json = json.dumps(data)
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        with db.get_connection() as (conn, cur):
            # استفاده از %s برای پستگرس
            cur.execute(
                "INSERT INTO tunnel_configs (owner_id, type, link, name, added_at) VALUES (%s, 'json', %s, %s, %s)",
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
        # FIX: psycopg2 cursor.execute() returns None; use cursor.fetchone()
        cur.execute("SELECT * FROM servers WHERE is_monitor_node=1")
        monitor = cur.fetchone()

    if not monitor:
        await msg.edit_text("❌ سرور مانیتورینگ فعال نیست.")
        return ConversationHandler.END

    ip, port, user = monitor['ip'], monitor['port'], monitor['username']
    password = sec.decrypt(monitor['password'])
    cmd = f"python3 /root/monitor_agent.py {shlex.quote(link)}"

    loop = asyncio.get_running_loop()
    # افزایش تایم‌اوت به 30 ثانیه برای ساب‌های سنگین
    ok, output = await ServerMonitor.run_remote_command(ip, port, user, password, cmd, 30)

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
                        "INSERT INTO tunnel_configs (owner_id, type, link, name, added_at, quality_score) VALUES (%s,'sub_item', %s,%s,%s,10)",
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
        # FIX: psycopg2 cursor.execute() returns None; use cursor.fetchone()
        cur.execute("SELECT * FROM servers WHERE is_monitor_node=1 AND is_active=1")
        monitor = cur.fetchone()
        # فقط ۵۰ کانفیگ آخر را برای سرعت بیشتر چک می‌کنیم (یا همه را بسته به نیاز)
        # FIX: psycopg2 cursor.execute() returns None; use cursor.fetchall()
        cur.execute(f"SELECT * FROM tunnel_configs WHERE owner_id=%s {query_filter} ORDER BY id DESC LIMIT 30", (uid,))
        configs = cur.fetchall()

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
        tasks.append(ServerMonitor.run_remote_command(ip, port, user, password, cmd, 15))

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
                                "UPDATE tunnel_configs SET last_status='OK', last_ping=%s, quality_score=%s WHERE id=%s",
                                (ping, score, cid)
                            )
                        else:
                            cur.execute("UPDATE tunnel_configs SET last_status='Fail' WHERE id=%s", (cid,))
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
            cur.execute("SELECT * FROM tunnel_configs WHERE owner_id=%s AND type='sub_source'", (uid,))
            subs = cur.fetchall()
            
        if not subs:
            await safe_edit_message(update, "❌ هیچ اشتراکی (Subscription) ثبت نکرده‌اید.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='tunnel_list_menu')]]))
            return

        txt = "📦 **لیست اشتراک‌های شما**\nبرای مدیریت یا آپدیت روی نام اشتراک بزنید:"
        reply_markup = keyboard.sub_list_kb(subs)
        
        await safe_edit_message(update, txt, reply_markup=reply_markup)
        return
    LIMIT = 10
    offset = (page - 1) * LIMIT
    base_query = "SELECT * FROM tunnel_configs WHERE owner_id=%s AND type != 'sub_source'"
    count_query = "SELECT COUNT(*) FROM tunnel_configs WHERE owner_id=%s AND type != 'sub_source'"
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
        # اصلاح اجرا: جدا کردن execute و fetchone + دریافت خروجی دیکشنری
        cur.execute(count_query, params)
        count_res = cur.fetchone()
        total_count = count_res['count'] if count_res else 0
        
        cur.execute(base_query, params)
        configs = cur.fetchall()

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
    
    reply_markup = keyboard.tunnel_list_kb(configs, page, total_pages, mode, delete_mode=delete_mode)
    
    await safe_edit_message(update, txt, reply_markup=reply_markup)
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
            
            tasks.append(ServerMonitor.run_remote_command(ip, port, user, password, cmd, 25))
        
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
async def handle_single_config_auto(update: Update, context: ContextTypes.DEFAULT_TYPE, link: str):
    """پردازش خودکار کانفیگ تکی بدون پرسش اضافی"""
    uid = update.effective_user.id
    
    # پیام اولیه
    status_msg = await update.message.reply_text(
        "⏳ **در حال بررسی و تست کانفیگ...**\n"
        "ربات در پس‌زمینه کانفیگ را آنالیز می‌کند."
    )
    
    # تعریف تسک برای اجرا در پس‌زمینه
    async def heavy_config_check_task():
        try:
            loop = asyncio.get_running_loop()
            
            # 1. دریافت اطلاعات سرور مانیتورینگ
            with db.get_connection() as (conn, cur):
                cur.execute("SELECT * FROM servers WHERE is_monitor_node=1 AND is_active=1")
                monitor = cur.fetchone()
            
            if not monitor:
                await status_msg.edit_text("❌ سرور مانیتورینگ (Iran Node) فعال نیست.")
                return

            # آپدیت پیام
            await status_msg.edit_text("🚀 **در حال تست اتصال به سرور تست...**")

            ip, port, user = monitor['ip'], monitor['port'], monitor['username']
            password = sec.decrypt(monitor['password'])
            
            # 2. اجرای دستور تست
            safe_link = shlex.quote(link)
            cmd = f"python3 /root/monitor_agent.py {safe_link}"
            
            ok, output = await ServerMonitor.run_remote_command(ip, port, user, password, cmd, 30)
            
            # 3. تحلیل خروجی
            data = extract_safe_json(output)
            
            if ok and data and (data.get('status') == 'OK' or 'protocol' in data):
                now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                final_name = data.get('extracted_name', f"Config_{int(time.time())}").replace('+', ' ').strip()
                score = data.get('score', 0)
                ping = data.get('ping', 0)
                
                # ذخیره در دیتابیس
                with db.get_connection() as (conn, cur):
                        cur.execute(
                            "INSERT INTO tunnel_configs (owner_id, type, link, name, added_at, quality_score, last_status, last_ping) VALUES (%s, 'single', %s, %s, %s, %s, 'OK', %s)", 
                            (uid, link, final_name, now, score, ping)
                        )
                        conn.commit()
                
                await status_msg.edit_text(
                    f"✅ **کانفیگ با موفقیت ثبت شد!**\n"
                    f"🏷 نام: `{final_name}`\n"
                    f"⭐️ امتیاز: `{score}/10`"
                )
                
                # نمایش دکمه بازگشت
                kb = [[InlineKeyboardButton("🔙 لیست کانفیگ‌ها", callback_data='tunnel_list_menu')]]
                await status_msg.reply_text("منو:", reply_markup=InlineKeyboardMarkup(kb))
            else:
                await status_msg.edit_text("❌ کانفیگ معتبر نیست یا سرور تست نتوانست به آن وصل شود.")

        except Exception as e:
            logger.error(f"Auto Add Error: {e}")
            try: await status_msg.edit_text(f"❌ خطا: {e}")
            except: pass
        finally:
             if uid in USER_ACTIVE_TASKS: del USER_ACTIVE_TASKS[uid]

    # ثبت تسک و پایان
    task = asyncio.create_task(heavy_config_check_task())
    USER_ACTIVE_TASKS[uid] = task
    return ConversationHandler.END
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
                ok, output = await ServerMonitor.run_remote_command(ip, port, user, password, cmd, 60)
                
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
        ok, output = await ServerMonitor.run_remote_command(ip, port, user, password, cmd, 60)
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
            
            # آپدیت دیتابیس با مقادیر واقعی تست سنگین (استفاده از %s)
            with db.get_connection() as (conn, cur):
                cur.execute(
                    "UPDATE tunnel_configs SET last_status='OK', last_ping=%s, last_jitter=%s, last_speed_up=%s, last_speed_down=%s, quality_score=%s WHERE id=%s",
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
            # ثبت خطا در دیتابیس (استفاده از %s)
            with db.get_connection() as (conn, cur):
                cur.execute("UPDATE tunnel_configs SET last_status='Fail', quality_score=0 WHERE id=%s", (cid,))
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

# ==============================================================================
# ⚙️ تنظیمات پیشرفته مانیتورینگ و ابزارها
# ==============================================================================

async def advanced_monitoring_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """منوی تنظیمات پیشرفته مانیتورینگ"""
    uid = update.effective_user.id
    if update.callback_query:
        await update.callback_query.answer()
        
    s_size = db.get_setting(uid, 'monitor_small_size') or '0.5'
    b_size = db.get_setting(uid, 'monitor_big_size') or '10'
    
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
    """منوی انتخاب حجم تست سبک"""
    uid = update.effective_user.id
    curr = db.get_setting(uid, 'monitor_small_size') or '0.5'
    reply_markup = keyboard.monitor_size_kb(curr, 'small')
    await safe_edit_message(update, "🔹 حجم دانلود برای **تست سبک** (Ping Check):", reply_markup=reply_markup)


async def set_big_size_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """منوی انتخاب حجم تست سنگین"""
    uid = update.effective_user.id
    curr = db.get_setting(uid, 'monitor_big_size') or '10'
    reply_markup = keyboard.monitor_size_kb(curr, 'big')
    await safe_edit_message(update, "🔸 حجم دانلود برای **تست سنگین** (Speed Test):", reply_markup=reply_markup)


async def set_big_interval_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """منوی انتخاب فاصله زمانی تست سنگین"""
    uid = update.effective_user.id
    curr = db.get_setting(uid, 'monitor_big_interval') or '60'
    reply_markup = keyboard.monitor_interval_kb(curr)
    await safe_edit_message(update, "⏰ فاصله زمانی اجرای **تست سنگین**:", reply_markup=reply_markup)


async def save_setting_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ذخیره تنظیمات انتخاب شده"""
    query = update.callback_query
    uid = update.effective_user.id
    data = query.data 
    
    parts = data.split('_')
    setting_type = parts[1] # small, big, int
    value = parts[2]
    
    # اگر گزینه 'دلخواه' انتخاب شده باشد
    if value == 'custom':
        map_txt = {
            'small': "✍️ حجم تست سبک (MB) را وارد کنید:", 
            'big': "✍️ حجم تست سنگین (MB) را وارد کنید:", 
            'int': "✍️ فاصله زمانی (دقیقه) را وارد کنید:"
        }
        state_map = {
            'small': GET_CUSTOM_SMALL_SIZE, 
            'big': GET_CUSTOM_BIG_SIZE, 
            'int': GET_CUSTOM_BIG_INTERVAL
        }
        
        await safe_edit_message(update, map_txt[setting_type], reply_markup=keyboard.get_cancel_markup())
        return state_map[setting_type]
    
    # ذخیره در دیتابیس
    key_map = {
        'small': 'monitor_small_size', 
        'big': 'monitor_big_size', 
        'int': 'monitor_big_interval'
    }
    db.set_setting(uid, key_map[setting_type], value)
    
    await query.answer("✅ ذخیره شد.")
    await advanced_monitoring_settings(update, context)


# --- هندلرهای ورودی‌های دلخواه (Custom Inputs) ---

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


# ==============================================================================
# 📄 نمایش جزئیات و ابزارهای کانفیگ
# ==============================================================================

async def show_config_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش جزئیات کامل یک کانفیگ"""
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
        await tunnel_list_menu(update, context)
        return

    # پیدا کردن والد (Parent) برای دکمه بازگشت در صورت ساب‌دامین بودن
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

    reply_markup = keyboard.config_detail_kb(cid, parent_id)
    await safe_edit_message(update, txt, reply_markup=reply_markup)


async def copy_config_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ارسال لینک کانفیگ جهت کپی"""
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
    """ایجاد و نمایش QR Code کانفیگ"""
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
        # FIX: Pass a size argument (>0.5) so agent outputs result lines for sub updates
        cmd = f"python3 -u /root/monitor_agent.py '{link}' 5.0"
        
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
        # FIX: RealDictCursor returns dict (e.g., {'count': ...})
        total_count = cur.fetchone().get('count', 0)
    
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
    """اجرای تست سبک (پینگ) برای همه کانفیگ‌ها در پس‌زمینه (Non-Blocking)"""
    query = update.callback_query
    uid = update.effective_user.id
    
    # 1. بررسی اینکه آیا کاربر تسک فعالی دارد یا خیر (جلوگیری از اسپم توسط یک نفر)
    if uid in USER_ACTIVE_TASKS and not USER_ACTIVE_TASKS[uid].done():
        try: await query.answer("⚠️ عملیات قبلی هنوز تمام نشده است!", show_alert=True)
        except: pass
        return

    # نمایش پیام موقت
    try: await query.answer("🚀 تست در پس‌زمینه شروع شد...", cache_time=1)
    except: pass
    
    status_msg = await query.message.reply_text(
        "⏳ **در حال بروزرسانی وضعیت (Ping Only)...**\n"
        "شما می‌توانید از ربات استفاده کنید، نتیجه این عملیات به زودی نمایش داده می‌شود."
    )
    
    # دریافت اطلاعات لازم (این بخش سریع است و نیاز به پس‌زمینه ندارد)
    with db.get_connection() as (conn, cur):
        cur.execute("SELECT * FROM tunnel_configs WHERE owner_id=%s", (uid,))
        configs = cur.fetchall()
        cur.execute("SELECT * FROM servers WHERE is_monitor_node=1 AND is_active=1")
        monitor = cur.fetchone()

    if not monitor:
        await status_msg.edit_text("❌ سرور مانیتورینگ فعال نیست.")
        return

    # --- تابع Wrapper برای اجرای در پس‌زمینه ---
    async def background_task():
        try:
            # اجرای عملیات اصلی تست
            await run_quick_ping_check(context, uid, configs, monitor)
            
            # حذف پیام انتظار
            try: await status_msg.delete()
            except: pass
            
            # بازگشت خودکار به داشبورد بروز شده (به کاربر اطلاع می‌دهد تمام شد)
            # چون update قدیمی است، باید پیام جدید بفرستیم یا ادیت کنیم
            # اینجا تابع داشبورد را صدا می‌زنیم تا لیست رفرش شود
            await config_stats_dashboard(update, context)
            
            # ارسال نوتیفیکیشن که تمام شد
            try: await context.bot.send_message(chat_id=uid, text="✅ **تست پینگ همگانی به پایان رسید.**")
            except: pass

        except Exception as e:
            logger.error(f"Background Ping Error: {e}")
        finally:
            # آزاد کردن قفل کاربر
            if uid in USER_ACTIVE_TASKS:
                del USER_ACTIVE_TASKS[uid]

    # 2. ایجاد تسک در پس‌زمینه (این خط جادویی است!)
    # ربات اینجا منتظر نمی‌ماند و بلافاصله به سراغ کاربر بعدی می‌رود
    task = asyncio.create_task(background_task())
    
    # ذخیره تسک برای مدیریت قفل کاربر
    USER_ACTIVE_TASKS[uid] = task
async def run_quick_ping_check(context, uid, configs, monitor):
    """لاجیک تست بسیار سریع و سبک (فقط پینگ) - بهینه شده و غیر مسدود کننده"""
    ip, port, user = monitor['ip'], monitor['port'], monitor['username']
    password = sec.decrypt(monitor['password'])
    loop = asyncio.get_running_loop()

    # پردازش دسته‌ای (۱۰ تایی برای سرعت بیشتر)
    chunk_size = 10
    
    # تعریف تابع کمکی برای آپدیت دیتابیس در ترد جداگانه
    def db_batch_update(results_chunk, config_chunk):
        with db.get_connection() as (conn, cur):
            for idx, (ok, output) in enumerate(results_chunk):
                cid = config_chunk[idx]['id']
                try:
                    res = extract_safe_json(output)
                    if res and res.get("status") == "OK":
                        ping = res.get('ping', 0)
                        jitter = res.get('jitter', 0)
                        new_score = 10
                        if ping > 1000: new_score = 2
                        elif ping > 500: new_score = 5
                        elif ping > 200: new_score = 8
                        
                        cur.execute(
                            "UPDATE tunnel_configs SET last_status='OK', last_ping=%s, last_jitter=%s, quality_score=%s WHERE id=%s",
                            (ping, jitter, new_score, cid)
                        )
                    else:
                        cur.execute("UPDATE tunnel_configs SET last_status='Fail' WHERE id=%s", (cid,))
                except:
                    cur.execute("UPDATE tunnel_configs SET last_status='Fail' WHERE id=%s", (cid,))
            conn.commit()

    for i in range(0, len(configs), chunk_size):
        chunk = configs[i:i+chunk_size]
        tasks = []
        
        for cfg in chunk:
            link_arg = cfg['link']
            if cfg['type'] == 'json' or link_arg.strip().startswith('{'):
                safe_link = link_arg.replace('"', '\\"')
                cmd = f'python3 /root/monitor_agent.py "{safe_link}" 0.2'
            else:
                cmd = f"python3 /root/monitor_agent.py '{link_arg}' 0.2"
            
            # تایم اوت کوتاه (۸ ثانیه) برای عدم معطلی
            # FIX: ServerMonitor.run_remote_command is async; do not call it in executor
            tasks.append(ServerMonitor.run_remote_command(ip, port, user, password, cmd, 8))
        
        results = await asyncio.gather(*tasks)
        
        # 🚀 آپدیت دیتابیس در بک‌گراند (بدون قفل کردن ربات)
        await loop.run_in_executor(EXECUTOR, db_batch_update, results, chunk)
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
    ok, data = await loop.run_in_executor(EXECUTOR, ServerMonitor.check_host_api, target)
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
        cur.execute("SELECT COUNT(*) as cnt FROM tunnel_configs WHERE owner_id=%s", (uid,))
        total = cur.fetchone()['cnt']

        # تعداد فعال
        cur.execute("SELECT COUNT(*) as cnt FROM tunnel_configs WHERE owner_id=%s AND last_status='OK'", (uid,))
        active = cur.fetchone()['cnt']

        # تعداد ساب‌ها
        cur.execute("SELECT COUNT(*) as cnt FROM tunnel_configs WHERE owner_id=%s AND type='sub_source'", (uid,))
        subs = cur.fetchone()['cnt']

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
    # FIX: ServerMonitor.set_dns is async; call directly (no executor)
    ok, msg = await ServerMonitor.set_dns(srv['ip'], srv['port'], srv['username'], real_pass, dns_type)
    
    if ok:
        await query.message.reply_text("✅ **DNS با موفقیت تغییر کرد.**")
    else:
        await query.message.reply_text(f"❌ خطا در تغییر DNS:\n{msg}")
    
    await server_detail(update, context, custom_sid=sid)

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /setting"""
    await settings_menu(update, context)
