#!/bin/bash

# رنگ‌ها برای زیبایی خروجی
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}🚀 Starting Sonar Radar Ultra Pro Installer...${NC}"

# 1. بررسی دسترسی روت
if [ "$EUID" -ne 0 ]; then 
  echo -e "${RED}❌ Please run as root (sudo bash ...)${NC}"
  exit
fi

# 2. نصب پیش‌نیازهای سیستمی
echo -e "${YELLOW}📦 Installing system dependencies...${NC}"
apt-get update && apt-get upgrade -y
apt-get install -y python3 python3-pip python3-venv git

# 3. کلون کردن ریپازیتوری
INSTALL_DIR="/opt/radar-sonar"
REPO_URL="https://github.com/Amirtn9/radar-sonar.git"

if [ -d "$INSTALL_DIR" ]; then
    echo -e "${YELLOW}⚠️ Directory exists. Updating repo...${NC}"
    cd "$INSTALL_DIR"
    git pull
else
    echo -e "${YELLOW}⬇️ Cloning repository...${NC}"
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# 4. ساخت محیط ایزوله (Virtual Environment)
echo -e "${YELLOW}🐍 Creating Python Virtual Environment...${NC}"
python3 -m venv venv
source venv/bin/activate

# 5. نصب کتابخانه‌های پایتون
echo -e "${YELLOW}📥 Installing Python libraries...${NC}"
pip install --upgrade pip
pip install -r requirements.txt

# 6. دریافت اطلاعات از کاربر (توکن و ادمین)
echo -e "${GREEN}⚙️ Configuration:${NC}"
read -p "🤖 Enter your Telegram Bot TOKEN: " USER_TOKEN
read -p "👤 Enter Super Admin Numeric ID: " USER_ADMIN_ID

# جایگزینی توکن و ادمین در فایل bot.py
# این دستور مقادیر پیش‌فرض داخل کد را با مقادیر وارد شده جایگزین می‌کند
sed -i "s/TOKEN = .*/TOKEN = '$USER_TOKEN'/" bot.py
sed -i "s/SUPER_ADMIN_ID = .*/SUPER_ADMIN_ID = $USER_ADMIN_ID/" bot.py

echo -e "${GREEN}✅ Configuration saved!${NC}"

# 7. ساخت سرویس Systemd (برای اجرای خودکار و دائم)
echo -e "${YELLOW}🔧 Setting up Systemd Service...${NC}"

SERVICE_FILE="/etc/systemd/system/sonar-bot.service"

cat <<EOF > $SERVICE_FILE
[Unit]
Description=Sonar Radar Ultra Pro Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python $INSTALL_DIR/bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# 8. فعال‌سازی و استارت ربات
systemctl daemon-reload
systemctl enable sonar-bot
systemctl restart sonar-bot

echo -e "${GREEN}=======================================${NC}"
echo -e "${GREEN}✅ Installation Completed Successfully!${NC}"
echo -e "${GREEN}🤖 Bot Service is running.${NC}"
echo -e "📜 To check logs: ${YELLOW}journalctl -u sonar-bot -f${NC}"
echo -e "🛑 To stop bot: ${YELLOW}systemctl stop sonar-bot${NC}"
echo -e "🔄 To restart bot: ${YELLOW}systemctl restart sonar-bot${NC}"
echo -e "${GREEN}=======================================${NC}"
