#!/bin/bash

# ==============================================================================
# 🦇 SONAR RADAR ULTRA MONITOR 1.0 - MANAGER
# ==============================================================================

# --- Configuration ---
INSTALL_DIR="/opt/radar-sonar"
SERVICE_NAME="sonar-bot"
REPO_URL="https://github.com/Amirtn9/radar-sonar.git"
RAW_URL="https://raw.githubusercontent.com/Amirtn9/radar-sonar/main"

# --- Colors (Modern Palette) ---
RESET='\033[0m'
BOLD='\033[1m'
CYAN='\033[0;36m'
BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
PURPLE='\033[0;35m'
BG_BLUE='\033[44m'

# --- Utils ---
function print_title() {
    clear
    echo -e "${PURPLE}${BOLD}"
    echo "      /\\                 /\\    "
    echo "     / \\'._   (\_/)   _.'/ \\   "
    echo "    /_.''._'--('.')--'_.''._\  "
    echo "    | \_ / \`  ~ ~  \`/ \_ / |  "
    echo "     \_/  \`/       \`'  \_/   "
    echo "           \`           \`      "
    echo -e "${RESET}"
    echo -e "   ${CYAN}${BOLD}🦇 SONAR RADAR ULTRA MONITOR 1.0${RESET}"
    echo -e "   ${BLUE}──────────────────────────────────${RESET}"
    echo ""
}

function print_success() {
    echo -e "${GREEN}${BOLD}✅ $1${RESET}"
}

function print_error() {
    echo -e "${RED}${BOLD}❌ $1${RESET}"
}

function print_info() {
    echo -e "${YELLOW}➤ $1...${RESET}"
}

function wait_enter() {
    echo ""
    read -p "Press [Enter] to continue..."
}

# --- Root Check ---
if [ "$EUID" -ne 0 ]; then 
  echo -e "${RED}❌ Please run as root.${RESET}"
  exit 1
fi

# ==============================================================================
# 🔧 CORE OPERATIONS
# ==============================================================================

function install_bot() {
    print_title
    echo -e "${BOLD}🚀 INSTALLATION STARTED...${RESET}\n"

    if systemctl is-active --quiet $SERVICE_NAME; then
        systemctl stop $SERVICE_NAME
    fi

    print_info "Updating system repositories"
    apt-get update -y > /dev/null 2>&1

    print_info "Installing system dependencies"
    apt-get install -y python3 python3-pip python3-venv git curl build-essential libssl-dev libffi-dev python3-dev > /dev/null 2>&1

    print_info "Setting up directories"
    # Backup
    if [ -f "$INSTALL_DIR/sonar_ultra_pro.db" ]; then cp "$INSTALL_DIR/sonar_ultra_pro.db" /tmp/sonar_backup.db; fi
    if [ -f "$INSTALL_DIR/secret.key" ]; then cp "$INSTALL_DIR/secret.key" /tmp/sonar_secret.key; fi
    
    rm -rf "$INSTALL_DIR"
    mkdir -p "$INSTALL_DIR"

    print_info "Downloading Sonar Radar source"
    if ! git clone "$REPO_URL" "$INSTALL_DIR" > /dev/null 2>&1; then
        curl -s -o "$INSTALL_DIR/bot.py" "$RAW_URL/bot.py"
        curl -s -o "$INSTALL_DIR/requirements.txt" "$RAW_URL/requirements.txt"
    fi

    # Restore
    if [ -f "/tmp/sonar_backup.db" ]; then mv /tmp/sonar_backup.db "$INSTALL_DIR/sonar_ultra_pro.db"; fi
    if [ -f "/tmp/sonar_secret.key" ]; then mv /tmp/sonar_secret.key "$INSTALL_DIR/secret.key"; fi

    print_info "Creating Virtual Environment"
    python3 -m venv "$INSTALL_DIR/venv"
    source "$INSTALL_DIR/venv/bin/activate"

    print_info "Installing Python libraries (This may take a while)"
    pip install --upgrade pip setuptools wheel > /dev/null 2>&1
    pip install "python-telegram-bot[job-queue]" paramiko cryptography jdatetime matplotlib requests > /dev/null 2>&1

    # Service File
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
    
    # Run Config if bot.py exists
    if [ -f "$INSTALL_DIR/bot.py" ]; then
        configure_token "install"
    else
        print_error "Download failed!"
        wait_enter
        return
    fi

    systemctl restart $SERVICE_NAME
    print_success "Installation Complete! Bot is running."
    wait_enter
}

function update_bot() {
    print_title
    echo -e "${BOLD}🔄 SMART UPDATE STARTED...${RESET}\n"
    
    if [ ! -d "$INSTALL_DIR" ]; then print_error "Bot is not installed."; wait_enter; return; fi

    systemctl stop $SERVICE_NAME

    print_info "Pulling latest code from GitHub"
    cd "$INSTALL_DIR" || exit
    git fetch --all > /dev/null 2>&1
    git reset --hard origin/main > /dev/null 2>&1
    git pull > /dev/null 2>&1

    print_info "Updating Python dependencies"
    if [ -d "venv" ]; then
        source "venv/bin/activate"
        pip install --upgrade "python-telegram-bot[job-queue]" paramiko cryptography jdatetime matplotlib requests > /dev/null 2>&1
    fi

    print_info "Restarting service"
    systemctl restart $SERVICE_NAME

    print_success "Update Finished Successfully."
    wait_enter
}

function full_restart_bot() {
    print_title
    echo -e "${BOLD}♻️ FULL SYSTEM RESTART...${RESET}\n"

    print_info "Stopping service"
    systemctl stop $SERVICE_NAME

    print_info "Killing zombie processes"
    # Kill all python processes running bot.py
    pkill -f "$INSTALL_DIR/bot.py" > /dev/null 2>&1
    # Optional: Kill all python3 if really needed (Commented for safety)
    # killall python3 > /dev/null 2>&1 
    sleep 2

    print_info "Starting service fresh"
    systemctl start $SERVICE_NAME

    if systemctl is-active --quiet $SERVICE_NAME; then
        print_success "Bot restarted successfully."
    else
        print_error "Failed to start bot. Check logs."
    fi
    wait_enter
}

function configure_token() {
    MODE=$1
    CONFIG_FILE="$INSTALL_DIR/bot.py"
    
    if [ ! -f "$CONFIG_FILE" ]; then 
        if [ "$MODE" != "install" ]; then
            print_error "Bot file not found."
            wait_enter
            return
        fi
    fi

    if [ "$MODE" != "install" ]; then
        print_title
        echo -e "${BOLD}⚙️ CONFIGURATION${RESET}\n"
    fi

    echo -e "${CYAN}🤖 Enter Telegram Bot Token:${RESET}"
    read -p ">> " TOKEN_INPUT

    echo -e "\n${CYAN}👤 Enter Admin Numeric ID:${RESET}"
    read -p ">> " ADMIN_INPUT

    if [ -n "$TOKEN_INPUT" ] && [ -n "$ADMIN_INPUT" ]; then
        sed -i "s/TOKEN = .*/TOKEN = '$TOKEN_INPUT'/" "$CONFIG_FILE"
        sed -i "s/SUPER_ADMIN_ID = .*/SUPER_ADMIN_ID = $ADMIN_INPUT/" "$CONFIG_FILE"
        print_success "Configuration saved."
    else
        print_error "Invalid input. Skipping config."
    fi

    if [ "$MODE" != "install" ]; then
        full_restart_bot
    fi
}

function uninstall_bot() {
    print_title
    echo -e "${RED}${BOLD}🗑️ UNINSTALLATION${RESET}\n"
    echo -e "⚠️  This will delete ALL data (Database, Logs, Config)."
    read -p "Are you sure? (y/n): " confirm
    if [[ "$confirm" == "y" || "$confirm" == "Y" ]]; then
        systemctl stop $SERVICE_NAME
        systemctl disable $SERVICE_NAME > /dev/null 2>&1
        rm -f /etc/systemd/system/$SERVICE_NAME.service
        systemctl daemon-reload
        rm -rf "$INSTALL_DIR"
        print_success "Bot completely removed."
    else
        echo "Cancelled."
    fi
    wait_enter
}

function view_logs() {
    clear
    echo -e "${GREEN}${BOLD}📜 LIVE LOGS (Press Ctrl+C to exit)${RESET}"
    echo -e "${BLUE}────────────────────────────────────────${RESET}"
    journalctl -u $SERVICE_NAME -f -n 50
}

# ==============================================================================
# 🖥 MAIN MENU LOOP
# ==============================================================================
while true; do
    print_title
    echo -e " ${GREEN}1)${RESET} 🚀 Install Bot"
    echo -e " ${GREEN}2)${RESET} 🔄 Update Bot"
    echo -e " ${GREEN}3)${RESET} ♻️  Restart (Force Kill & Start)"
    echo -e " ${GREEN}4)${RESET} 📜 View Logs"
    echo -e " ${GREEN}5)${RESET} ⚙️  Config (Token & Admin)"
    echo -e " ${GREEN}6)${RESET} 🗑️  Uninstall"
    echo -e " ${RED}7) ❌ Exit${RESET}"
    echo ""
    echo -e "${BLUE}──────────────────────────────────${RESET}"
    read -p " Select option [1-7]: " OPTION

    case $OPTION in
        1) install_bot ;;
        2) update_bot ;;
        3) full_restart_bot ;;
        4) view_logs ;;
        5) configure_token "menu" ;;
        6) uninstall_bot ;;
        7) clear; echo -e "${CYAN}Good Bye! 👋${RESET}"; exit ;;
        *) echo -e "${RED}Invalid Option.${RESET}"; sleep 1 ;;
    esac
done
