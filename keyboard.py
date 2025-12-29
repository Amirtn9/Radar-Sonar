from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from settings import SUBSCRIPTION_PLANS

# ==============================================================================
# 🔙 GENERAL & COMMON BUTTONS
# ==============================================================================

def get_cancel_markup():
    """دکمه انصراف استاندارد"""
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 انصراف", callback_data='cancel_flow')]])

def back_btn(callback_data='main_menu', text="🔙 بازگشت"):
    """دکمه بازگشت تکی"""
    return InlineKeyboardMarkup([[InlineKeyboardButton(text, callback_data=callback_data)]])

# ==============================================================================
# 🏠 MAIN MENUS & USER PROFILE
# ==============================================================================

# --- جایگزین تابع main_menu_kb قبلی شود ---
def main_menu_kb(user_id, is_monitor_ready, admin_id):
    """منوی اصلی ربات (ویرایش شده: انتقال دکمه‌ها به تنظیمات)"""
    kb = [
        # ردیف ۱: حساب کاربری
        [InlineKeyboardButton("👤 حساب کاربری و کیف پول", callback_data='open_account_menu')],
        
        # ردیف ۲: خرید و دعوت
        [InlineKeyboardButton("🛍 خرید اشتراک", callback_data='wallet_menu'),
         InlineKeyboardButton("🤝 دعوت (رایگان)", callback_data='referral_menu')],
        
        # ردیف ۳: سرویس‌ها
        [InlineKeyboardButton("➕ افزودن سرویس جدید", callback_data='open_add_menu')],
        [InlineKeyboardButton("📂 مدیریت لیست‌ها (سرور/کانفیگ)", callback_data='open_lists_menu')],
        
        # ردیف ۴: داشبورد
        [InlineKeyboardButton("📊 داشبورد شبکه", callback_data='status_dashboard')],
        
        # ردیف ۵: فقط دکمه تنظیمات باقی ماند
        [InlineKeyboardButton("⚙️ تنظیمات پیشرفته", callback_data='settings_menu')]
    ]

    if user_id == admin_id:
        kb.insert(0, [InlineKeyboardButton("🤖 مدیریت ربات", callback_data='admin_panel_main')])

    return InlineKeyboardMarkup(kb)
def account_dashboard_kb():
    """منوی داخلی حساب کاربری و کیف پول"""
    kb = [
        [InlineKeyboardButton("🔑 دریافت توکن پنل وب", callback_data='gen_web_token')],
        [InlineKeyboardButton("➕ افزایش موجودی (به زودی)", callback_data='top_up_wallet')], # دکمه نمایشی برای آینده
        [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(kb)

def user_profile_kb():
    """دکمه‌های پروفایل کاربری"""
    kb = [
        [InlineKeyboardButton("🔑 دریافت توکن پنل وب (Web Token)", callback_data='gen_web_token')],
        [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(kb)

def add_service_selection_kb():
    """منوی انتخاب نوع سرویس برای افزودن"""
    kb = [
        [InlineKeyboardButton("🖥 افزودن سرور (VPS)", callback_data='add_server')],
        [InlineKeyboardButton("🚇 افزودن تانل (Tunnel)", callback_data='add_tunnel_config')],
        [InlineKeyboardButton("🔙 بازگشت", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(kb)

def lists_dashboard_kb():
    """منوی انتخاب بین لیست سرورها و کانفیگ‌ها"""
    kb = [
        [InlineKeyboardButton("📋 لیست سرورها (VPS)", callback_data='list_groups_for_servers')],
        [InlineKeyboardButton("📑 لیست کانفیگ‌ها (Tunnel)", callback_data='tunnel_list_menu')],
        [InlineKeyboardButton("🔙 بازگشت", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(kb)
# ==============================================================================
# 🤖 ADMIN PANEL KEYBOARDS
# ==============================================================================

def admin_main_kb():
    """منوی اصلی پنل مدیریت"""
    kb = [
        [InlineKeyboardButton("👥 مدیریت کاربران", callback_data='admin_users_page_1')],
        [InlineKeyboardButton("➕ افزودن دستی کاربر", callback_data='add_new_admin')],
        [InlineKeyboardButton("📢 ارسال پیام همگانی", callback_data='admin_broadcast_start')],
        [InlineKeyboardButton("🔎 جستجوی کاربر", callback_data='admin_search_start'),
         InlineKeyboardButton("📄 لیست متنی", callback_data='admin_users_text')],
        [InlineKeyboardButton("📥 دریافت بکاپ", callback_data='admin_backup_get'),
         InlineKeyboardButton("📤 بازنشانی بکاپ", callback_data='admin_backup_restore_start')],
        [InlineKeyboardButton("🔑 دریافت کلید (Backup Key)", callback_data='admin_key_backup_get'),
         InlineKeyboardButton("🗝 بازیابی کلید (Restore Key)", callback_data='admin_key_restore_start')],
        [InlineKeyboardButton("📜 لیست کل سرورهای کاربران (Full Report)", callback_data='admin_all_servers_1')],
        [InlineKeyboardButton("💳 تنظیمات پرداخت و ولت", callback_data='admin_pay_settings')],
        [InlineKeyboardButton("📡 تنظیمات مانیتورینگ تانل", callback_data='monitor_settings_panel')],
        [InlineKeyboardButton("🔙 بازگشت", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(kb)

def admin_users_list_kb(users, page, total_pages):
    """لیست کاربران همراه با صفحه‌بندی"""
    kb = []
    for u in users:
        status = "🔴" if u['is_banned'] else "🟢"
        name = u['full_name'] if u['full_name'] else "Unknown"
        kb.append([InlineKeyboardButton(f"{status} {name} | {u['user_id']}",
                                        callback_data=f"admin_u_manage_{u['user_id']}")])

    nav_btns = []
    if page > 1: nav_btns.append(InlineKeyboardButton("◀️ قبلی", callback_data=f'admin_users_page_{page - 1}'))
    if page < total_pages: nav_btns.append(InlineKeyboardButton("بعدی ▶️", callback_data=f'admin_users_page_{page + 1}'))

    if nav_btns: kb.append(nav_btns)
    kb.append([InlineKeyboardButton("🔙 بازگشت به مدیریت", callback_data='admin_panel_main')])
    return InlineKeyboardMarkup(kb)

def admin_user_manage_kb(user_id, plan_type, is_banned):
    """مدیریت تکی کاربر"""
    plan_action = "تبدیل به عادی ⬇️" if plan_type == 1 else "ارتقا به پریمیوم 💎"
    
    kb = [
        [InlineKeyboardButton("➕ تمدید (30 روز)", callback_data=f'admin_u_addtime_{user_id}'),
         InlineKeyboardButton("📅 تنظیم زمان دستی", callback_data=f'admin_u_settime_{user_id}')],
        [InlineKeyboardButton(plan_action, callback_data=f'admin_u_toggleplan_{user_id}')],
        [InlineKeyboardButton("🔢 تغییر لیمیت سرور", callback_data=f'admin_u_limit_{user_id}')],
        [InlineKeyboardButton("مسدود/رفع مسدود", callback_data=f'admin_u_ban_{user_id}'),
         InlineKeyboardButton("🗑 حذف", callback_data=f'admin_u_del_{user_id}')],
        [InlineKeyboardButton("🖥 مشاهده لیست کامل سرورها و کیفیت 📊", callback_data=f'admin_u_servers_{user_id}')],
        [InlineKeyboardButton("🔙 بازگشت", callback_data='admin_users_page_1')]
    ]
    return InlineKeyboardMarkup(kb)

def admin_pay_settings_kb(methods):
    """مدیریت روش‌های پرداخت"""
    kb = []
    for m in methods:
        icon = "🏦" if m['type'] == 'card' else "💎"
        kb.append([InlineKeyboardButton(f"🗑 حذف {icon} {m['network']}", callback_data=f'del_pay_method_{m["id"]}')])

    kb.append([InlineKeyboardButton("➕ افزودن کارت بانکی", callback_data='add_pay_method_card')])
    kb.append([InlineKeyboardButton("➕ افزودن ولت کریپتو", callback_data='add_pay_method_crypto')])
    kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data='admin_panel_main')])
    return InlineKeyboardMarkup(kb)

# ==============================================================================
# 🖥 SERVER MANAGEMENT KEYBOARDS
# ==============================================================================

def server_detail_kb(sid, server_ip, is_premium):
    """منوی مدیریت یک سرور خاص"""
    # دکمه‌های شرطی
    btn_clean = InlineKeyboardButton("🧹 پاکسازی دیسک", callback_data=f'act_cleandisk_{sid}')
    btn_script = InlineKeyboardButton("🛠 اسکریپت", callback_data=f'act_installscript_{sid}') if is_premium else InlineKeyboardButton("🔒 اسکریپت", callback_data=f'act_installscript_{sid}')

    kb = [
        [
            InlineKeyboardButton("📊 نمودار", callback_data=f'act_chart_{sid}'),
            InlineKeyboardButton("🔄 تازه‌سازی", callback_data=f'detail_{sid}')
        ],
        [
            InlineKeyboardButton("🇮🇷 وضعیت شبکه (ایران)", callback_data=f'act_checkhost_{sid}_{server_ip}'),
            InlineKeyboardButton("🏢 دیتاسنتر", callback_data=f'act_datacenter_{sid}')
        ],
        [
            InlineKeyboardButton("📝 گزارش جامع جهانی", callback_data=f'act_fullreport_{sid}')
        ],
        [
            InlineKeyboardButton("🚀 تست سرعت", callback_data=f'act_speedtest_{sid}'),
            InlineKeyboardButton("🧹 پاکسازی RAM", callback_data=f'act_clearcache_{sid}')
        ],
        [
            InlineKeyboardButton("⚙️ DNS", callback_data=f'act_dns_{sid}'),
            InlineKeyboardButton("📥 نصب Speedtest", callback_data=f'act_installspeed_{sid}')
        ],
        [
            InlineKeyboardButton("📦 بروزرسانی Repo", callback_data=f'act_repoupdate_{sid}'),
            InlineKeyboardButton("💎 ارتقاء کامل", callback_data=f'act_fullupdate_{sid}')
        ],
        [
            InlineKeyboardButton("📅 ویرایش انقضا", callback_data=f'act_editexpiry_{sid}'),
            InlineKeyboardButton("⚠️ راه‌اندازی مجدد", callback_data=f'act_reboot_{sid}')
        ],
        [btn_clean, btn_script],
        [InlineKeyboardButton("❌ حذف سرور", callback_data=f'act_del_{sid}')],
        [InlineKeyboardButton("🔙 بازگشت به لیست", callback_data='list_groups_for_servers')]
    ]
    return InlineKeyboardMarkup(kb)

def add_server_method_kb():
    """انتخاب روش افزودن سرور"""
    kb = [
        [InlineKeyboardButton("🧙‍♂️ مرحله به مرحله (ویزارد)", callback_data='add_method_step')],
        [InlineKeyboardButton("⚡️ افزودن سریع (خطی/چندگانه)", callback_data='add_method_linear')],
        [InlineKeyboardButton("🔙 انصراف", callback_data='cancel_flow')]
    ]
    return InlineKeyboardMarkup(kb)

def groups_menu_kb(groups):
    """لیست گروه‌ها"""
    kb = [[InlineKeyboardButton(f"🗑 {g['name']}", callback_data=f'delgroup_{g["id"]}')] for g in groups]
    kb.append([InlineKeyboardButton("➕ گروه جدید", callback_data='add_group')])
    kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data='settings_menu')])
    return InlineKeyboardMarkup(kb)

def server_list_kb(servers, group_id=None, is_all=False):
    """لیست سرورها برای نمایش"""
    kb = []
    for s in servers:
        status_icon = "🟢" if s['last_status'] == 'Online' else "🔴"
        kb.append(
            [InlineKeyboardButton(f"{status_icon} {s['name']}  |  {s['ip']}", callback_data=f'detail_{s["id"]}')])
    
    back_cb = 'list_groups_for_servers'
    kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data=back_cb)])
    return InlineKeyboardMarkup(kb)

def select_group_kb(groups):
    """انتخاب گروه هنگام افزودن سرور"""
    kb = [[InlineKeyboardButton(f"📁 {g['name']}", callback_data=str(g['id']))] for g in groups]
    kb.append([InlineKeyboardButton("فایل اصلی (بدون گروه)", callback_data="0")])
    kb.append([InlineKeyboardButton("🔙 انصراف", callback_data="cancel_flow")])
    return kb # این تابع لیست برمیگرداند چون در کد اصلی تبدیل به مارک‌آپ میشود

def group_selection_kb(groups):
    """لیست گروه‌ها برای مشاهده سرورها"""
    kb = [[InlineKeyboardButton("🔗 همه سرورها (یکجا)", callback_data='list_all')]] + [
        [InlineKeyboardButton(f"📁 {g['name']}", callback_data=f'listsrv_{g["id"]}')] for g in groups]
    kb.append([InlineKeyboardButton("📄 سرورهای بدون گروه", callback_data='listsrv_0')])
    kb.append([InlineKeyboardButton("🔙 منوی اصلی", callback_data='main_menu')])
    return InlineKeyboardMarkup(kb)

def dns_selection_kb(sid):
    """منوی انتخاب DNS"""
    kb = [
        [InlineKeyboardButton("Google (8.8.8.8)", callback_data=f'setdns_google_{sid}'),
         InlineKeyboardButton("Cloudflare (1.1.1.1)", callback_data=f'setdns_cloudflare_{sid}')],
        [InlineKeyboardButton("Quad9 (Security)", callback_data=f'setdns_quad9_{sid}'),
         InlineKeyboardButton("OpenDNS (Cisco)", callback_data=f'setdns_opendns_{sid}')],
        [InlineKeyboardButton("AdGuard (No Ads)", callback_data=f'setdns_adguard_{sid}'),
         InlineKeyboardButton("Yandex (Basic)", callback_data=f'setdns_yandex_{sid}')],
        [InlineKeyboardButton("Comodo (Secure)", callback_data=f'setdns_comodo_{sid}'),
         InlineKeyboardButton("Shecan (Iran)", callback_data=f'setdns_shecan_{sid}')],
        [InlineKeyboardButton("🔙 بازگشت", callback_data=f'detail_{sid}')]
    ]
    return InlineKeyboardMarkup(kb)

# ==============================================================================
# 📊 DASHBOARD & MONITORING
# ==============================================================================

def dashboard_main_kb():
    """منوی داشبورد"""
    kb = [
        [
            InlineKeyboardButton("📊 وضعیت کانفیگ‌ها (Tunnel)", callback_data='show_config_stats'),
            InlineKeyboardButton("🖥 وضعیت سرورها (VPS)", callback_data='show_server_stats')
        ],
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(kb)

def server_stats_kb():
    """دکمه‌های زیر پیام وضعیت سرورها"""
    kb = [
        [InlineKeyboardButton("🔄 بروزرسانی", callback_data='show_server_stats')],
        [InlineKeyboardButton("⚡️ مدیریت سرورها", callback_data='manage_servers_list')],
        [InlineKeyboardButton("🔙 بازگشت به داشبورد", callback_data='status_dashboard')]
    ]
    return InlineKeyboardMarkup(kb)

def manage_monitor_list_kb(servers):
    """لیست سرورها برای خاموش/روشن کردن مانیتورینگ"""
    kb = [[InlineKeyboardButton(f"{'🟢' if s['is_active'] else '🔴'} | {s['name']}", callback_data=f'toggle_active_{s["id"]}')] for s in servers]
    kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data='status_dashboard')])
    return InlineKeyboardMarkup(kb)

def dashboard_sort_kb(current_sort):
    """منوی مرتب‌سازی داشبورد"""
    def mark(val):
        return "✅ " if val == current_sort else ""

    kb = [
        [InlineKeyboardButton(f"{mark('uptime')}بیشترین آپتایم ⏱", callback_data='set_dash_sort_uptime')],
        [InlineKeyboardButton(f"{mark('traffic')}بیشترین مصرف ترافیک 📡", callback_data='set_dash_sort_traffic')],
        [InlineKeyboardButton(f"{mark('resource')}بیشترین درگیری منابع (CPU/RAM) 🔥", callback_data='set_dash_sort_resource')],
        [InlineKeyboardButton(f"{mark('id')}قدیمی‌ترین (پیش‌فرض) 📅", callback_data='set_dash_sort_id')],
        [InlineKeyboardButton("🔙 بازگشت به داشبورد", callback_data='status_dashboard')]
    ]
    return InlineKeyboardMarkup(kb)

# ==============================================================================
# ⚙️ SETTINGS KEYBOARDS
# ==============================================================================

def settings_main_kb():
    """منوی اصلی تنظیمات (ویرایش شده: افزودن گزینه‌های جدید و ادغام)"""
    kb = [
        # گزینه ادغام شده (جایگزین خودکارسازی و مانیتورینگ قدیم)
        [
            InlineKeyboardButton("⏰ زمان‌بندی و هشدارها", callback_data='menu_schedules')
        ],
        # گزینه‌های منتقل شده از صفحه اصلی
        [
            InlineKeyboardButton("📂 گروه‌بندی سرورها", callback_data='groups_menu'),
            InlineKeyboardButton("⚡️ عملیات همگانی سرورها (فوری)", callback_data='global_ops_menu')
        ],
        # گزینه‌های قبلی که دست نخورده‌اند
        [
            InlineKeyboardButton("📢 مدیریت کانال‌های ارسال", callback_data='channels_menu')
        ],
        [
            InlineKeyboardButton("📄 دریافت گزارش کلی ✊🏽", callback_data='send_general_report')
        ],
        [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(kb)
def schedules_settings_kb(srv_alert_icon, srv_toggle, conf_alert_icon, conf_toggle):
    """منوی جدید ادغام شده: زمان‌بندی‌ها + مانیتورینگ (نسخه کامل)"""
    kb = [
        # --- بخش ۱: زمان‌بندی ارسال اعلان‌ها (Reports) ---
        [InlineKeyboardButton("📋 تنظیم زمان‌بندی اعلان‌ها (Reports)", callback_data='header_none')],
        [InlineKeyboardButton("📊 گزارش وضعیت سرورها", callback_data='settings_cron'),
         InlineKeyboardButton("📡 گزارش وضعیت کانفیگ‌ها", callback_data='settings_conf_cron')],
        
        # --- بخش ۲: وظایف خودکار (Automation) ---
        [InlineKeyboardButton("🤖 وظایف خودکار سیستم", callback_data='header_none')],
        [InlineKeyboardButton("🔄 آپدیت مخازن", callback_data='auto_up_menu'),
         InlineKeyboardButton("⚠️ ریبوت خودکار", callback_data='auto_reboot_menu')],
        
        # --- بخش ۳: تنظیمات حساسیت (Alerts) ---
        [InlineKeyboardButton("🎚 تنظیمات هشدار (Alerts)", callback_data='header_none')],
        # ردیف هشدارها: سرور + کانفیگ
        [InlineKeyboardButton(f"🚨 قطعی سرور: {srv_alert_icon}", callback_data=f'toggle_downalert_{srv_toggle}'),
         InlineKeyboardButton(f"❌ قطعی کانفیگ: {conf_alert_icon}", callback_data=f'toggle_confalert_{conf_toggle}')],
        
        [InlineKeyboardButton("🧠 لیمیت منابع (CPU/RAM)", callback_data='settings_thresholds'),
         InlineKeyboardButton("🚀 تست سرعت پیشرفته", callback_data='advanced_monitoring_settings')],
        
        # --- بازگشت ---
        [InlineKeyboardButton("🔙 بازگشت به تنظیمات", callback_data='settings_menu')]
    ]
    return InlineKeyboardMarkup(kb)
def automation_settings_kb():
    """تنظیمات خودکارسازی"""
    kb = [
        [InlineKeyboardButton("⏰ تنظیم زمان‌بندی گزارش (Cron)", callback_data='settings_cron')],
        [InlineKeyboardButton("🔄 تنظیم آپدیت خودکار مخازن", callback_data='auto_up_menu')],
        [InlineKeyboardButton("⚠️ تنظیم ریبوت خودکار سرورها", callback_data='auto_reboot_menu')],
        [InlineKeyboardButton("🚀 تنظیمات پیشرفته تست سرعت", callback_data='advanced_monitoring_settings')],
        [InlineKeyboardButton("🔙 بازگشت", callback_data='settings_menu')]
    ]
    return InlineKeyboardMarkup(kb)

def monitoring_settings_kb(alert_icon, toggle_val):
    """تنظیمات مانیتورینگ"""
    kb = [
        [InlineKeyboardButton(f"🚨 هشدار قطعی: {alert_icon}", callback_data=f'toggle_downalert_{toggle_val}')],
        [InlineKeyboardButton("🎚 تغییر آستانه مصرف منابع (Limits)", callback_data='settings_thresholds')],
        [InlineKeyboardButton("🔙 بازگشت", callback_data='settings_menu')]
    ]
    return InlineKeyboardMarkup(kb)

def settings_cron_kb(current_val):
    """تنظیمات زمان‌بندی گزارش سرور (زمان‌های دقیق)"""
    def get_label(text, value):
        return f"✅ {text}" if str(value) == str(current_val) else f"🔘 {text}"

    # مقادیر بر حسب ثانیه
    kb = [
        [InlineKeyboardButton(get_label("۱۵ دقیقه", 900), callback_data='setcron_900'),
         InlineKeyboardButton(get_label("۳۰ دقیقه", 1800), callback_data='setcron_1800')],
        
        [InlineKeyboardButton(get_label("۱ ساعت", 3600), callback_data='setcron_3600'),
         InlineKeyboardButton(get_label("۲ ساعت", 7200), callback_data='setcron_7200'),
         InlineKeyboardButton(get_label("۳ ساعت", 10800), callback_data='setcron_10800')],
         
        [InlineKeyboardButton(get_label("۱۲ ساعت", 43200), callback_data='setcron_43200'),
         InlineKeyboardButton(get_label("۲۴ ساعت", 86400), callback_data='setcron_86400')],
         
        [InlineKeyboardButton(get_label("❌ غیرفعال", 0), callback_data='setcron_0')],
        [InlineKeyboardButton("🔙 بازگشت", callback_data='menu_schedules')]
    ]
    return InlineKeyboardMarkup(kb)

def config_cron_kb(current_val):
    """تنظیمات زمان‌بندی گزارش کانفیگ‌ها (زمان‌های دقیق)"""
    def get_label(text, value):
        return f"✅ {text}" if str(value) == str(current_val) else f"🔘 {text}"

    # مقادیر بر حسب دقیقه
    kb = [
        [InlineKeyboardButton(get_label("۱۵ دقیقه", 15), callback_data='setconfcron_15'),
         InlineKeyboardButton(get_label("۳۰ دقیقه", 30), callback_data='setconfcron_30')],
        
        [InlineKeyboardButton(get_label("۱ ساعت", 60), callback_data='setconfcron_60'),
         InlineKeyboardButton(get_label("۲ ساعت", 120), callback_data='setconfcron_120'),
         InlineKeyboardButton(get_label("۳ ساعت", 180), callback_data='setconfcron_180')],
        
        [InlineKeyboardButton(get_label("۱۲ ساعت", 720), callback_data='setconfcron_720'),
         InlineKeyboardButton(get_label("۲۴ ساعت", 1440), callback_data='setconfcron_1440')],
        
        [InlineKeyboardButton(get_label("❌ غیرفعال", 0), callback_data='setconfcron_0')],
        [InlineKeyboardButton("🔙 بازگشت", callback_data='menu_schedules')]
    ]
    return InlineKeyboardMarkup(kb)

def config_cron_kb(current_val):
    """تنظیمات زمان‌بندی گزارش کانفیگ‌ها (گزینه‌های جدید)"""
    def get_label(text, value):
        return f"✅ {text}" if str(value) == str(current_val) else f"🔘 {text}"

    # مقادیر بر حسب دقیقه (چون در هندلر کانفیگ دقیقه ذخیره میکنیم)
    kb = [
        [InlineKeyboardButton(get_label("۱۵ دقیقه", 15), callback_data='setconfcron_15'),
         InlineKeyboardButton(get_label("۳۰ دقیقه", 30), callback_data='setconfcron_30')],
        
        [InlineKeyboardButton(get_label("۱ ساعت", 60), callback_data='setconfcron_60'),
         InlineKeyboardButton(get_label("۲ ساعت", 120), callback_data='setconfcron_120'),
         InlineKeyboardButton(get_label("۳ ساعت", 180), callback_data='setconfcron_180')],
        
        [InlineKeyboardButton(get_label("۱۲ ساعت", 720), callback_data='setconfcron_720'),
         InlineKeyboardButton(get_label("۲۴ ساعت", 1440), callback_data='setconfcron_1440')],
        
        [InlineKeyboardButton(get_label("❌ غیرفعال", 0), callback_data='setconfcron_0')],
        [InlineKeyboardButton("🔙 بازگشت", callback_data='menu_schedules')]
    ]
    return InlineKeyboardMarkup(kb)
def config_cron_kb(current_val):
    """تنظیمات زمان‌بندی گزارش کانفیگ‌ها"""
    def get_label(text, value):
        # اگر انتخاب شده بود تیک سبز، وگرنه دایره خالی
        return f"✅ {text}" if str(value) == str(current_val) else f"🔘 {text}"

    kb = [
        [InlineKeyboardButton(get_label("هر ۱ ساعت", 60), callback_data='setconfcron_60'),
         InlineKeyboardButton(get_label("هر ۳ ساعت", 180), callback_data='setconfcron_180')],
        
        [InlineKeyboardButton(get_label("هر ۶ ساعت", 360), callback_data='setconfcron_360'),
         InlineKeyboardButton(get_label("هر ۱۲ ساعت", 720), callback_data='setconfcron_720')],
        
        [InlineKeyboardButton(get_label("هر ۲۴ ساعت", 1440), callback_data='setconfcron_1440')],
        
        [InlineKeyboardButton(get_label("❌ غیرفعال (خاموش)", 0), callback_data='setconfcron_0')],
        [InlineKeyboardButton("🔙 بازگشت", callback_data='menu_schedules')]
    ]
    return InlineKeyboardMarkup(kb)

def resource_limits_kb(cpu, ram, disk):
    """تنظیم لیمیت منابع"""
    kb = [
        [InlineKeyboardButton(f"تغییر حد CPU ({cpu}%)", callback_data='set_cpu_limit')],
        [InlineKeyboardButton(f"تغییر حد RAM ({ram}%)", callback_data='set_ram_limit')],
        [InlineKeyboardButton(f"تغییر حد Disk ({disk}%)", callback_data='set_disk_limit')],
        [InlineKeyboardButton("🔙 بازگشت", callback_data='menu_schedules')]
    ]
    return InlineKeyboardMarkup(kb)
def auto_update_kb(curr_val):
    """تنظیم آپدیت خودکار"""
    def st(val):
        return "✅" if str(val) == str(curr_val) else ""

    kb = [
        [InlineKeyboardButton(f"{st(6)} هر ۶ ساعت", callback_data='set_autoup_6'), InlineKeyboardButton(f"{st(12)} هر ۱۲ ساعت", callback_data='set_autoup_12')],
        [InlineKeyboardButton(f"{st(24)} هر ۲۴ ساعت", callback_data='set_autoup_24'), InlineKeyboardButton(f"{st(48)} هر ۴۸ ساعت", callback_data='set_autoup_48')],
        [InlineKeyboardButton(f"{st(0)} ❌ غیرفعال", callback_data='set_autoup_0')],
        [InlineKeyboardButton("🔙 بازگشت", callback_data='menu_schedules')]
    ]
    return InlineKeyboardMarkup(kb)

def auto_reboot_kb():
    """منوی ریبوت خودکار"""
    kb = [
        [InlineKeyboardButton("⚙️ تنظیم زمان‌بندی جدید", callback_data='start_set_reboot')],
        [InlineKeyboardButton("❌ غیرفعال‌سازی", callback_data='disable_reboot')],
        [InlineKeyboardButton("🔙 بازگشت", callback_data='menu_schedules')]
    ]
    return InlineKeyboardMarkup(kb)

def reboot_freq_kb(time_str):
    """انتخاب فرکانس ریبوت"""
    kb = [
        [InlineKeyboardButton(f"هر روز ساعت {time_str}", callback_data=f'savereb_1_{time_str}')],
        [InlineKeyboardButton(f"هر ۲ روز ساعت {time_str}", callback_data=f'savereb_2_{time_str}')],
        [InlineKeyboardButton(f"هفته‌ای یکبار (۷ روز)", callback_data=f'savereb_7_{time_str}')],
        [InlineKeyboardButton(f"هر ۲ هفته یکبار", callback_data=f'savereb_14_{time_str}')],
        [InlineKeyboardButton(f"ماهانه (۳۰ روز)", callback_data=f'savereb_30_{time_str}')],
        [InlineKeyboardButton("🔙 انصراف", callback_data='cancel_flow')]
    ]
    return InlineKeyboardMarkup(kb)

def advanced_monitor_kb(s_size, b_size):
    """تنظیمات پیشرفته مانیتورینگ"""
    kb = [
        [InlineKeyboardButton(f"🔹 حجم تست سبک ({s_size} MB)", callback_data='set_small_size_menu')],
        [InlineKeyboardButton(f"🔸 حجم تست سنگین ({b_size} MB)", callback_data='set_big_size_menu')],
        [InlineKeyboardButton(f"⏰ فاصله زمانی تست سنگین", callback_data='set_big_interval_menu')],
        [InlineKeyboardButton("🔙 بازگشت", callback_data='menu_schedules')]
    ]
    return InlineKeyboardMarkup(kb)
def monitor_size_kb(curr, setting_type):
    """انتخاب سایز دانلود برای تست"""
    def get_mark(current, target):
        return "✅ " if str(current) == str(target) else ""
    
    cb_prefix = f"save_{setting_type}" # save_small or save_big
    
    if setting_type == 'small':
        opts = [('0.5', '0.5'), ('1', '1'), ('2', '2')]
    else:
        opts = [('10', '10'), ('20', '20'), ('50', '50')]

    row1 = [InlineKeyboardButton(f"{get_mark(curr, o[0])}{o[1]} MB", callback_data=f'{cb_prefix}_{o[0]}') for o in opts[:2]]
    row2 = [InlineKeyboardButton(f"{get_mark(curr, opts[2][0])}{opts[2][1]} MB", callback_data=f'{cb_prefix}_{opts[2][0]}'), InlineKeyboardButton("✍️ عدد دلخواه", callback_data=f'{cb_prefix}_custom')]
    
    kb = [row1, row2, [InlineKeyboardButton("🔙 بازگشت", callback_data='advanced_monitoring_settings')]]
    return InlineKeyboardMarkup(kb)

def monitor_interval_kb(curr):
    """انتخاب اینتروال تست سنگین"""
    def get_mark(current, target):
        return "✅ " if str(current) == str(target) else ""
    
    kb = [
        [InlineKeyboardButton(f"{get_mark(curr, '60')}هر ۱ ساعت", callback_data='save_int_60'), InlineKeyboardButton(f"{get_mark(curr, '120')}هر ۲ ساعت", callback_data='save_int_120')],
        [InlineKeyboardButton(f"{get_mark(curr, '360')}هر ۶ ساعت", callback_data='save_int_360'), InlineKeyboardButton("✍️ زمان دلخواه", callback_data='save_int_custom')],
        [InlineKeyboardButton("🔙 بازگشت", callback_data='advanced_monitoring_settings')]
    ]
    return InlineKeyboardMarkup(kb)

# ==============================================================================
# 🚇 TUNNEL & CONFIG KEYBOARDS
# ==============================================================================

def tunnel_menu_kb():
    """منوی افزودن تانل"""
    kb = [
        [InlineKeyboardButton("📦 سابسکریپشن (استخراج همه)", callback_data='type_sub')],
        [InlineKeyboardButton("👤 کانفیگ تکی", callback_data='type_single')],
        [InlineKeyboardButton("🔙 انصراف", callback_data='cancel_flow')]
    ]
    return InlineKeyboardMarkup(kb)

def tunnel_list_mode_kb():
    """منوی انتخاب نوع لیست کانفیگ + دکمه بروزرسانی همگانی"""
    kb = [
        [InlineKeyboardButton("🚀 بروزرسانی و تست همگانی (Full) ♻️", callback_data='mass_update_test_all')],
        [InlineKeyboardButton("👤 کانفیگ‌های تکی", callback_data='list_mode_single')],
        [InlineKeyboardButton("📦 کانفیگ‌های سابسکریپشن", callback_data='list_mode_sub')],
        [InlineKeyboardButton("🔗 مشاهده همه (یکجا)", callback_data='list_mode_all')],
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(kb)

def tunnel_list_kb(configs, page, total_pages, mode, delete_mode=False):
    """لیست کانفیگ‌ها با صفحه‌بندی و قابلیت حذف"""
    kb = []
    
    # 1. ساخت دکمه‌های لیست (حالت نمایش یا حالت حذف)
    for c in configs:
        if delete_mode:
            # --- حالت حذف ---
            display_name = c['name'][:20] + "..." if len(c['name']) > 20 else c['name']
            btn_text = f"❌ حذف: {display_name}"
            # کالبک جدید برای حذف آیتم: del_item_{id}_{mode}_{page}
            callback = f"del_list_item_{c['id']}_{mode}_{page}"
        else:
            # --- حالت عادی (تست و نمایش) ---
            if c['last_status'] == 'OK':
                status_icon = "🟢"
                ping_display = f"({c['last_ping']}ms)"
            elif c['last_status'] == 'Fail':
                status_icon = "🔴"
                ping_display = "(قطع)"
            else:
                status_icon = "⚪️"
                ping_display = "(ناشناس)"
            
            display_name = c['name'][:20] + "..." if len(c['name']) > 20 else c['name']
            btn_text = f"{status_icon} {display_name} {ping_display}"
            callback = f"test_conf_{c['id']}"
        
        kb.append([InlineKeyboardButton(btn_text, callback_data=callback)])

    # 2. دکمه کنترل حالت حذف (دقیقاً بالای دکمه‌های بعدی/قبلی)
    # state=1 یعنی حالت حذف روشن، state=0 یعنی خاموش
    if delete_mode:
        toggle_btn = InlineKeyboardButton("🔙 خروج از حالت حذف", callback_data=f'list_mode_{mode}_{page}_0')
    else:
        toggle_btn = InlineKeyboardButton("🗑 حذف کانفیگ (چندتایی)", callback_data=f'list_mode_{mode}_{page}_1')
    
    kb.append([toggle_btn])

    # 3. دکمه‌های صفحه‌بندی (Next/Prev)
    nav = []
    # state فعلی (0 یا 1) باید در صفحه‌بندی حفظ شود
    state_flag = "1" if delete_mode else "0"
    
    if page > 1: 
        nav.append(InlineKeyboardButton("◀️ قبلی", callback_data=f'list_mode_{mode}_{page-1}_{state_flag}'))
    
    if page < total_pages: 
        nav.append(InlineKeyboardButton("بعدی ▶️", callback_data=f'list_mode_{mode}_{page+1}_{state_flag}'))
    
    if nav: kb.append(nav)
    
    # 4. دکمه بازگشت اصلی
    kb.append([InlineKeyboardButton("🔙 بازگشت به منو", callback_data='tunnel_list_menu')])
    
    return InlineKeyboardMarkup(kb)
def sub_list_kb(subs):
    """لیست سابسکریپشن‌ها (فولدرها)"""
    kb = []
    for s in subs:
        kb.append([InlineKeyboardButton(f"📂 {s['name']}", callback_data=f'manage_sub_{s["id"]}')])
    kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data='tunnel_list_menu')])
    return InlineKeyboardMarkup(kb)

def manage_sub_kb(items, sub_id, page, max_pages, sub_name):
    """مدیریت آیتم‌های داخل یک ساب"""
    kb = []
    for item in items:
        status = "🟢" if item['last_status'] == 'OK' else "🔴"
        clean_name = item['name'].replace(f"{sub_name} | ", "").strip()[:20]
        ping = f"{item['last_ping']}ms" if item['last_ping'] > 0 else "N/A"
        
        kb.append([InlineKeyboardButton(
            f"{status} {clean_name} | 📶 {ping}", 
            callback_data=f'conf_detail_{item["id"]}'
        )])

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("◀️ قبلی", callback_data=f'manage_sub_{sub_id}_{page-1}'))
    if page < max_pages:
        nav.append(InlineKeyboardButton("بعدی ▶️", callback_data=f'manage_sub_{sub_id}_{page+1}'))
    if nav:
        kb.append(nav)

    kb.append([InlineKeyboardButton("🔄 آپدیت وضعیت و حجم", callback_data=f'update_sub_{sub_id}')])
    kb.append([InlineKeyboardButton("📥 دریافت همه لینک‌ها (فایل)", callback_data=f'get_sub_links_{sub_id}')])
    kb.append([InlineKeyboardButton("🗑 حذف کل اشتراک", callback_data=f'del_sub_full_{sub_id}')])
    kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data='tunnel_list_menu')])
    return InlineKeyboardMarkup(kb)

def config_detail_kb(cid, parent_id=None):
    """جزئیات و عملیات روی یک کانفیگ تکی"""
    kb = [
        [InlineKeyboardButton("📋 کپی لینک کانفیگ", callback_data=f'copy_conf_{cid}')],
        [InlineKeyboardButton("🖼 دریافت QR Code", callback_data=f'qr_conf_{cid}')],
        [InlineKeyboardButton("⚡️ تست سرعت تکی", callback_data=f'test_conf_{cid}')]
    ]
    
    if parent_id:
        kb.append([InlineKeyboardButton("🔙 بازگشت به لیست اشتراک", callback_data=f'manage_sub_{parent_id}')])
    else:
        kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data='tunnel_list_menu')])
    return InlineKeyboardMarkup(kb)

def config_test_result_kb(cid):
    """دکمه‌های زیر نتیجه تست کانفیگ"""
    kb = [
        [
            InlineKeyboardButton("🔄 تست مجدد (دقیق)", callback_data=f'test_conf_{cid}'),
            InlineKeyboardButton("👁 مشاهده کانفیگ", callback_data=f'view_conf_{cid}')
        ],
        [
            InlineKeyboardButton("🗑 حذف کانفیگ", callback_data=f'del_conf_{cid}'),
            InlineKeyboardButton("🔙 بازگشت به لیست", callback_data='tunnel_list_menu')
        ]
    ]
    return InlineKeyboardMarkup(kb)

def monitor_node_kb(is_set):
    """منوی سرور مانیتورینگ ایران"""
    if not is_set:
        kb = [
            [InlineKeyboardButton("🇮🇷 فعال‌سازی تست از ایران (نصب خودکار)", callback_data='set_iran_monitor_server')],
            [InlineKeyboardButton("🔙 بازگشت", callback_data='admin_panel_main')]
        ]
    else:
        kb = [
            [InlineKeyboardButton("🔄 بررسی بروزرسانی و تعمیر فایل‌ها", callback_data='update_monitor_node')],
            [InlineKeyboardButton("🗑 قطع ارتباط و حذف فایل‌ها", callback_data='delete_monitor_node')],
            [InlineKeyboardButton("🔙 بازگشت", callback_data='admin_panel_main')]
        ]
    return InlineKeyboardMarkup(kb)

# ==============================================================================
# 💰 WALLET & PAYMENT
# ==============================================================================

def wallet_main_kb():
    """منوی کیف پول"""
    kb = [
        [InlineKeyboardButton("🥉 خرید برنزی", callback_data='buy_plan_bronze')],
        [InlineKeyboardButton("🥈 خرید نقره‌ای", callback_data='buy_plan_silver')],
        [InlineKeyboardButton("🥇 خرید طلایی", callback_data='buy_plan_gold')],
        [InlineKeyboardButton("🔙 بازگشت", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(kb)

def payment_method_kb():
    """انتخاب روش پرداخت"""
    kb = [
        [InlineKeyboardButton("💳 کارت به کارت (Toman)", callback_data='pay_method_card')],
        [InlineKeyboardButton("💎 ارز دیجیتال (TRX/USDT)", callback_data='pay_method_tron')],
        [InlineKeyboardButton("🔙 بازگشت", callback_data='wallet_menu')]
    ]
    return InlineKeyboardMarkup(kb)

def confirm_payment_kb(pay_id):
    """دکمه تایید پرداخت"""
    kb = [
        [InlineKeyboardButton("✅ پرداخت کردم (ارسال رسید)", callback_data=f'confirm_pay_{pay_id}')],
        [InlineKeyboardButton("🔙 انصراف", callback_data='wallet_menu')]
    ]
    return InlineKeyboardMarkup(kb)

def admin_receipt_kb(pay_id):
    """دکمه‌های زیر رسید برای ادمین"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تایید و فعال‌سازی", callback_data=f'admin_approve_pay_{pay_id}')],
        [InlineKeyboardButton("❌ رد کردن (فیک)", callback_data=f'admin_reject_pay_{pay_id}')]
    ])

def referral_kb(invite_link):
    """دکمه اشتراک گذاری لینک دعوت"""
    kb = [
        [InlineKeyboardButton("📲 اشتراک‌گذاری سریع", url=f"https://t.me/share/url?url={invite_link}&text=ربات%20مدیریت%20سرور%20حرفه%20ای%20سونار")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(kb)

# ==============================================================================
# 🌍 GLOBAL OPS
# ==============================================================================

def global_ops_kb():
    """منوی عملیات همگانی"""
    kb = [
        [InlineKeyboardButton("🔄 آپدیت مخازن (همه سرورها)", callback_data='glob_act_update')],
        [InlineKeyboardButton("🧹 پاکسازی RAM (همه سرورها)", callback_data='glob_act_ram')],
        [InlineKeyboardButton("🗑 پاکسازی دیسک (همه سرورها)", callback_data='glob_act_disk')],
        [InlineKeyboardButton("🛠 سرویس کامل (Full Service)", callback_data='glob_act_full')],
        [InlineKeyboardButton("🔙 بازگشت", callback_data='settings_menu')]
    ]
    return InlineKeyboardMarkup(kb)

def admin_global_report_kb(page, total_pages):
    """منوی گزارش سرورهای فعال برای ادمین"""
    kb = [
        [InlineKeyboardButton("📥 دریافت اطلاعات تمامی سرورهای فعال", callback_data='admin_full_report_global')],
        [InlineKeyboardButton("🔎 دریافت اطلاعات سرور بر اساس آیدی عددی", callback_data='admin_search_servers_by_uid_start')]
    ]
    
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("◀️ قبلی", callback_data=f'admin_all_servers_{page-1}'))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton("بعدی ▶️", callback_data=f'admin_all_servers_{page+1}'))

    if nav_row:
        kb.append(nav_row)
    kb.append([InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data='admin_panel_main')])
    return InlineKeyboardMarkup(kb)

# ------------------ Admin: Logs & Services ------------------

def admin_logs_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🦇 لاگ BOT", callback_data="admin_log_bot"),
         InlineKeyboardButton("🦇 لاگ API", callback_data="admin_log_api")],
        [InlineKeyboardButton("🦇 لاگ AGENT", callback_data="admin_log_agent"),
         InlineKeyboardButton("🦇 لاگ PostgreSQL", callback_data="admin_log_postgres")],
        [InlineKeyboardButton("⬅️ بازگشت", callback_data="admin_panel_main")]
    ])

def admin_services_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 ریستارت BOT", callback_data="svc_restart_bot"),
         InlineKeyboardButton("ℹ️ وضعیت BOT", callback_data="svc_status_bot")],
        [InlineKeyboardButton("🔄 ریستارت API", callback_data="svc_restart_api"),
         InlineKeyboardButton("ℹ️ وضعیت API", callback_data="svc_status_api")],
        [InlineKeyboardButton("🔄 ریستارت AGENT", callback_data="svc_restart_agent"),
         InlineKeyboardButton("ℹ️ وضعیت AGENT", callback_data="svc_status_agent")],
        [InlineKeyboardButton("⬅️ بازگشت", callback_data="admin_panel_main")]
    ])
