#!/bin/bash

# ==============================================================================
# 🦇 SONAR RADAR ULTRA MONITOR 1.0 - MANAGER
# ==============================================================================

# --- Configuration ---
INSTALL_DIR="/opt/radar-sonar"
SERVICE_NAME="sonar-bot"
REPO_URL="https://github.com/Amirtn9/radar-sonar.git"
RAW_URL="https://raw.githubusercontent.com/Amirtn9/radar-sonar/main"

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'

# --- Header & Logo ---
function show_header() {
    clear
    echo -e "${PURPLE}"
    echo "      /\\                 /\\    "
    echo "     / \\'._   (\_/)   _.'/ \\   "
    echo "    /_.''._'--('.')--'_.''._\  "
    echo "    | \_ / \`  ~ ~  \`/ \_ / |  "
    echo "     \_/  \`/       \`'  \_/   "
    echo "           \`           \`      "
    echo -e "${NC}"
    echo -e "${CYAN}   🦇 SONAR RADAR ULTRA MONITOR 1.0 🦇${NC}"
    echo -e "${BLUE} ==========================================${NC}"
    sleep 0.3
}

# --- Root Check ---
if [ "$EUID" -ne 0 ]; then 
  echo -e "${RED}❌ لطفا با دسترسی روت اجرا کنید (sudo).${NC}"
  exit 1
fi

# --- Install Whiptail if missing ---
if ! command -v whiptail &> /dev/null; then
    echo -e "${YELLOW}📦 نصب ابزارهای گرافیکی...${NC}"
    apt-get update -y > /dev/null 2>&1
    apt-get install -y whiptail > /dev/null 2>&1
fi

# ==============================================================================
# 🔧 FUNCTIONS
# ==============================================================================

function install_bot() {
    if systemctl is-active --quiet $SERVICE_NAME; then systemctl stop $SERVICE_NAME; fi
    
    {
        echo 10; echo "XXX\n🔄 در حال آپدیت مخازن سیستم...\nXXX"
        apt-get update -y > /dev/null 2>&1
        
        echo 30; echo "XXX\n📦 نصب پیش‌نیازهای پایتون و سیستم...\nXXX"
        apt-get install -y python3 python3-pip python3-venv git curl build-essential libssl-dev libffi-dev python3-dev > /dev/null 2>&1
        
        echo 50; echo "XXX\n📂 آماده‌سازی دایرکتوری‌ها...\nXXX"
        if [ -f "$INSTALL_DIR/sonar_ultra_pro.db" ]; then cp "$INSTALL_DIR/sonar_ultra_pro.db" /tmp/sonar_backup.db; fi
        if [ -f "$INSTALL_DIR/secret.key" ]; then cp "$INSTALL_DIR/secret.key" /tmp/sonar_secret.key; fi
        rm -rf "$INSTALL_DIR"; mkdir -p "$INSTALL_DIR"
        
        echo 60; echo "XXX\n📥 دریافت فایل‌های ربات...\nXXX"
        if ! git clone "$REPO_URL" "$INSTALL_DIR" > /dev/null 2>&1; then
            curl -s -o "$INSTALL_DIR/bot.py" "$RAW_URL/bot.py"
            curl -s -o "$INSTALL_DIR/requirements.txt" "$RAW_URL/requirements.txt"
        fi
        
        # Restore Backups
        if [ -f "/tmp/sonar_backup.db" ]; then mv /tmp/sonar_backup.db "$INSTALL_DIR/sonar_ultra_pro.db"; fi
        if [ -f "/tmp/sonar_secret.key" ]; then mv /tmp/sonar_secret.key "$INSTALL_DIR/secret.key"; fi

        echo 80; echo "XXX\n🐍 ساخت محیط ایزوله (VirtualEnv)...\nXXX"
        python3 -m venv "$INSTALL_DIR/venv"
        source "$INSTALL_DIR/venv/bin/activate"
        
        echo 90; echo "XXX\n📚 نصب کتابخانه‌های مورد نیاز...\nXXX"
        pip install --upgrade pip setuptools wheel > /dev/null 2>&1
        pip install "python-telegram-bot[job-queue]" paramiko cryptography jdatetime matplotlib requests > /dev/null 2>&1
        
        echo 100
    } | whiptail --title "نصب ربات" --gauge "در حال نصب Sonar Radar..." 8 60 0

    if [ ! -f "$INSTALL_DIR/bot.py" ]; then whiptail --msgbox "❌ خطا در دانلود فایل‌ها." 8 45; return; fi

    configure_token_gui "install"

    # Create Service
    cat <<EOF > /etc/systemd/system/$SERVICE_NAME.service
[Unit]
Description=Sonar Radar Ultra Pro Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python $INSTALL_DIR/bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable $SERVICE_NAME > /dev/null 2>&1
    systemctl restart $SERVICE_NAME
    whiptail --msgbox "✅ نصب با موفقیت انجام شد!\n🦇 Sonar Radar فعال است." 8 45
}

function update_bot() {
    if [ ! -d "$INSTALL_DIR" ]; then whiptail --msgbox "❌ ربات نصب نیست!" 8 45; return; fi
    
    systemctl stop $SERVICE_NAME
    {
        echo 20; echo "XXX\n📥 دریافت آخرین تغییرات از گیت‌هاب...\nXXX"
        cd "$INSTALL_DIR" || exit
        git fetch --all > /dev/null 2>&1
        git reset --hard origin/main > /dev/null 2>&1
        git pull > /dev/null 2>&1
        
        echo 60; echo "XXX\n♻️ آپدیت کتابخانه‌های پایتون...\nXXX"
        if [ -d "venv" ]; then
            source "venv/bin/activate"
            pip install --upgrade "python-telegram-bot[job-queue]" paramiko cryptography jdatetime matplotlib requests > /dev/null 2>&1
        fi
        
        echo 90; echo "XXX\n🚀 استارت مجدد سرویس...\nXXX"
        systemctl restart $SERVICE_NAME
        echo 100
    } | whiptail --title "بروزرسانی" --gauge "در حال آپدیت هوشمند..." 8 60 0
    
    whiptail --msgbox "✅ ربات و تمام فایل‌ها آپدیت شدند." 8 45
}

function full_restart_bot() {
    {
        echo 10; echo "XXX\n🛑 توقف سرویس ربات...\nXXX"
        systemctl stop $SERVICE_NAME
        
        echo 40; echo "XXX\n🔫 کشتن تمام پروسه‌های درگیر (Kill Processes)...\nXXX"
        # کشتن هر پروسه پایتونی که مربوط به بات باشد برای جلوگیری از تداخل
        pkill -f "$INSTALL_DIR/bot.py" > /dev/null 2>&1
        killall python3 > /dev/null 2>&1  # احتیاط (ممکن است سایر اسکریپت‌ها را ببندد، اگر سرور اشتراکی است این خط را بردارید)
        sleep 2
        
        echo 80; echo "XXX\n🚀 استارت مجدد سرویس...\nXXX"
        systemctl start $SERVICE_NAME
        
        echo 100
    } | whiptail --title "ریستارت سیستمی" --gauge "در حال پاکسازی و ریستارت..." 8 60 0
    
    if systemctl is-active --quiet $SERVICE_NAME; then
        whiptail --msgbox "✅ ربات با موفقیت ریستارت شد.\nهمه پروسه‌های اضافه پاکسازی شدند." 8 50
    else
        whiptail --msgbox "❌ مشکل در استارت ربات. لطفا لاگ‌ها را چک کنید." 8 50
    fi
}

function configure_token_gui() {
    MODE=$1
    CONFIG_FILE="$INSTALL_DIR/bot.py"
    if [ ! -f "$CONFIG_FILE" ]; then return; fi

    TOKEN=$(whiptail --inputbox "🤖 توکن جدید ربات را وارد کنید:" 10 60 --title "تنظیمات توکن" 3>&1 1>&2 2>&3)
    if [ $? -ne 0 ]; then return; fi

    ADMIN_ID=$(whiptail --inputbox "👤 آیدی عددی ادمین (Admin ID):" 10 60 --title "تنظیمات ادمین" 3>&1 1>&2 2>&3)
    if [ $? -ne 0 ]; then return; fi

    sed -i "s/TOKEN = .*/TOKEN = '$TOKEN'/" "$CONFIG_FILE"
    sed -i "s/SUPER_ADMIN_ID = .*/SUPER_ADMIN_ID = $ADMIN_ID/" "$CONFIG_FILE"

    if [ "$MODE" != "install" ]; then
        full_restart_bot
    fi
}

function uninstall_bot() {
    if (whiptail --title "⚠️ حذف خطرناک" --yesno "آیا مطمئن هستید؟\n\n❌ کل دیتابیس و اطلاعات پاک می‌شود و قابل برگشت نیست!" 10 60); then
        systemctl stop $SERVICE_NAME
        systemctl disable $SERVICE_NAME > /dev/null 2>&1
        rm -f /etc/systemd/system/$SERVICE_NAME.service
        systemctl daemon-reload
        rm -rf "$INSTALL_DIR"
        whiptail --msgbox "🗑️ ربات و تمام اطلاعات آن به طور کامل حذف شد." 8 45
    fi
}

function view_logs() {
    clear
    echo -e "${GREEN}📜 نمایش زنده لاگ‌ها (برای خروج Ctrl+C را بزنید)...${NC}"
    echo -e "${YELLOW}---------------------------------------------------${NC}"
    journalctl -u $SERVICE_NAME -f -n 50
}

# ==============================================================================
# 🖥 MAIN MENU
# ==============================================================================
while true; do
    show_header
    
    OPTION=$(whiptail --title "🦇 Sonar Radar Ultra Monitor 1.0" --menu "یکی از گزینه‌ها را انتخاب کنید:" 20 70 10 \
    "1" "🚀 نصب ربات (Install Bot)" \
    "2" "🔄 آپدیت هوشمند (Update Bot)" \
    "3" "♻️ ریستارت کامل و پاکسازی (Full Restart)" \
    "4" "📜 مشاهده لاگ‌های زنده (Logs)" \
    "5" "⚙️ تغییر توکن و آیدی ادمین (Config)" \
    "6" "🗑️ حذف کامل ربات (Uninstall)" \
    "7" "❌ خروج (Exit)" 3>&1 1>&2 2>&3)

    exitstatus=$?
    if [ $exitstatus != 0 ]; then exit; fi

    case $OPTION in
        1) install_bot ;;
        2) update_bot ;;
        3) full_restart_bot ;;
        4) view_logs ;;
        5) configure_token_gui "menu" ;;
        6) uninstall_bot ;;
        7) clear; echo "خداحافظ 👋"; exit ;;
    esac
done
