#!/bin/bash

# ==============================================================================
# 🚀 SONAR RADAR ULTRA PRO - INSTALLER & MANAGER
# ==============================================================================

# --- Configuration ---
INSTALL_DIR="/opt/radar-sonar"
SERVICE_NAME="sonar-bot"
# IMPORTANT: Pointing to the current directory assuming you have the files locally 
# or update this to your git repo if needed. 
# For this script, we assume we overwrite bot.py with local content or pull from git.
# Since you provided the bot code directly, we will create the file manually in this script.
REPO_URL="https://github.com/Amirtn9/radar-sonar.git" 

# --- Colors & Styling ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# --- ASCII Header ---
function show_header() {
    clear
    echo -e "${CYAN}"
    echo "   _____  ____  _   _          _____ "
    echo "  / ____|/ __ \| \ | |   /\   |  __ \\"
    echo " | (___ | |  | |  \| |  /  \  | |__) |"
    echo "  \___ \| |  | | . ' | / /\ \ |  _  / "
    echo "  ____) | |__| | |\  |/ ____ \| | \ \ "
    echo " |_____/ \____/|_| \_/_/    \_\_|  \_\\"
    echo "                                      "
    echo "      🚀 RADAR ULTRA PRO MANAGER      "
    echo -e "${NC}"
    echo -e "${BLUE}==========================================${NC}"
    sleep 0.5
}

# --- Root Check ---
if [ "$EUID" -ne 0 ]; then 
  echo -e "${RED}❌ Error: Please run as root (sudo bash install.sh)${NC}"
  exit 1
fi

# --- Dependencies Check (Whiptail) ---
if ! command -v whiptail &> /dev/null; then
    echo -e "${YELLOW}📦 Installing necessary tools (whiptail)...${NC}"
    apt-get update > /dev/null 2>&1
    apt-get install -y whiptail > /dev/null 2>&1
fi

# ==============================================================================
# 🔧 CORE FUNCTIONS
# ==============================================================================

# 1. Install Bot Logic
function install_bot() {
    show_header
    
    # Progress Bar for System Updates
    {
        echo 10
        echo "XXX\nUpdating package lists...\nXXX"
        apt-get update > /dev/null 2>&1
        echo 40
        echo "XXX\nInstalling Python & Git...\nXXX"
        apt-get install -y python3 python3-pip python3-venv git > /dev/null 2>&1
        echo 80
        echo "XXX\nFinalizing dependencies...\nXXX"
        sleep 1
        echo 100
    } | whiptail --title "System Update" --gauge "Preparing system environment..." 8 60 0

    # Setup Directory
    if [ ! -d "$INSTALL_DIR" ]; then
        mkdir -p "$INSTALL_DIR"
        echo -e "${GREEN}📂 Created directory: $INSTALL_DIR${NC}"
    fi

    # Create Python Virtual Environment
    if [ ! -d "$INSTALL_DIR/venv" ]; then
        whiptail --infobox "🐍 Creating Python Virtual Environment..." 8 50
        python3 -m venv "$INSTALL_DIR/venv"
    fi

    # Install Python Libraries
    source "$INSTALL_DIR/venv/bin/activate"
    whiptail --infobox "📥 Installing Python Libraries (This may take a while)..." 8 50
    pip install --upgrade pip > /dev/null 2>&1
    pip install python-telegram-bot[job-queue] requests paramiko cryptography jdatetime matplotlib > /dev/null 2>&1

    # --- WRITE BOT CODE (Important Step) ---
    # Since you provided the code, we write it directly to ensure it's the latest version.
    whiptail --infobox "📝 Writing application code..." 8 50
    
    # NOTE: Ideally, you should curl this from a Gist or Repo. 
    # For now, we assume the file 'bot.py' exists next to this script or we download it.
    # Here we download the raw bot.py if you have uploaded it, otherwise we touch it.
    # *Adjust this part to download YOUR specific bot.py content*
    
    # Option A: Download from your repo (Recommended)
    if [ -d "$INSTALL_DIR/.git" ]; then
        cd "$INSTALL_DIR" && git pull > /dev/null 2>&1
    else
        git clone "$REPO_URL" "$INSTALL_DIR" > /dev/null 2>&1
    fi
    
    # Option B (Fallback): If you want to paste the code inside this script (Heredoc)
    # You can uncomment the block below and paste the python code between EOFs if you don't use git.
    
    # Configure Bot
    configure_bot_gui "install"

    # Setup Systemd Service
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

    # Enable & Start
    systemctl daemon-reload
    systemctl enable $SERVICE_NAME > /dev/null 2>&1
    systemctl restart $SERVICE_NAME

    whiptail --msgbox "✅ Installation Complete!\n\n🤖 Bot is now running in the background." 10 50
}

# 2. Configuration GUI
function configure_bot_gui() {
    MODE=$1
    CONFIG_FILE="$INSTALL_DIR/bot.py"

    if [ ! -f "$CONFIG_FILE" ]; then
        whiptail --msgbox "❌ bot.py not found! Please install the bot first." 8 45
        return
    fi

    TOKEN=$(whiptail --inputbox "🤖 Enter Telegram Bot TOKEN:" 10 60 --title "Bot Setup" 3>&1 1>&2 2>&3)
    if [ $? -ne 0 ]; then return; fi

    ADMIN_ID=$(whiptail --inputbox "👤 Enter Super Admin Numeric ID:" 10 60 --title "Bot Setup" 3>&1 1>&2 2>&3)
    if [ $? -ne 0 ]; then return; fi

    # Update File using sed
    sed -i "s/TOKEN = .*/TOKEN = '$TOKEN'/" "$CONFIG_FILE"
    sed -i "s/SUPER_ADMIN_ID = .*/SUPER_ADMIN_ID = $ADMIN_ID/" "$CONFIG_FILE"

    if [ "$MODE" != "install" ]; then
        if (whiptail --title "Restart Required" --yesno "Configuration saved. Restart bot now?" 8 45); then
            systemctl restart $SERVICE_NAME
            whiptail --msgbox "✅ Bot Restarted with new config." 8 40
        fi
    fi
}

# 3. Uninstall Logic
function uninstall_bot() {
    if (whiptail --title "⚠️ DANGER ZONE" --yesno "Are you sure you want to completely REMOVE Sonar Radar?\n\nThis will delete:\n- All source codes\n- Database & Settings\n- System Service" 12 60); then
        
        {
            echo 20
            echo "XXX\nStopping service...\nXXX"
            systemctl stop $SERVICE_NAME
            systemctl disable $SERVICE_NAME > /dev/null 2>&1
            
            echo 50
            echo "XXX\nRemoving systemd service...\nXXX"
            rm -f /etc/systemd/system/$SERVICE_NAME.service
            systemctl daemon-reload
            
            echo 80
            echo "XXX\nDeleting files...\nXXX"
            rm -rf "$INSTALL_DIR"
            
            echo 100
        } | whiptail --gauge "Uninstalling..." 8 50 0

        whiptail --msgbox "🗑️ Uninstallation Complete." 8 40
    fi
}

# 4. Logs Viewer
function view_logs() {
    clear
    echo -e "${GREEN}📜 Showing Live Logs (Press Ctrl+C to return)...${NC}"
    echo -e "${YELLOW}-----------------------------------------------------${NC}"
    journalctl -u $SERVICE_NAME -f -n 50
}

# 5. Database Status (New)
function check_status() {
    STATUS=$(systemctl is-active $SERVICE_NAME)
    if [ "$STATUS" == "active" ]; then
        ICON="🟢"
        MSG="Running"
    else
        ICON="🔴"
        MSG="Stopped"
    fi
    
    DB_SIZE="Unknown"
    if [ -f "$INSTALL_DIR/sonar_ultra_pro.db" ]; then
        DB_SIZE=$(du -h "$INSTALL_DIR/sonar_ultra_pro.db" | cut -f1)
    fi

    whiptail --msgbox "📊 Bot Status Information\n\n$ICON Service Status: $MSG\n💾 Database Size: $DB_SIZE\n📂 Install Path: $INSTALL_DIR" 12 50
}

# ==============================================================================
# 🖥 MAIN MENU
# ==============================================================================
while true; do
    show_header
    
    OPTION=$(whiptail --title "🚀 Sonar Radar Manager" --menu "Choose an option:" 18 70 10 \
    "1" "📥 Install / Update (Force Update)" \
    "2" "⚙️ Configure (Token & Admin ID)" \
    "3" "⏯️ Restart Bot" \
    "4" "🛑 Stop Bot" \
    "5" "📜 Live Logs" \
    "6" "📊 Check Status" \
    "7" "🗑️ Uninstall" \
    "8" "❌ Exit" 3>&1 1>&2 2>&3)

    exitstatus=$?
    if [ $exitstatus != 0 ]; then exit; fi

    case $OPTION in
        1) install_bot ;;
        2) configure_bot_gui "menu" ;;
        3) 
            systemctl restart $SERVICE_NAME
            whiptail --msgbox "🔄 Service Restarted." 8 30
            ;;
        4) 
            systemctl stop $SERVICE_NAME
            whiptail --msgbox "🛑 Service Stopped." 8 30
            ;;
        5) view_logs ;;
        6) check_status ;;
        7) uninstall_bot ;;
        8) clear; exit ;;
    esac
done
