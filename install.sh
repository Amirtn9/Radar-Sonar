#!/bin/bash

# ==============================================================================
# 🦇 SONAR RADAR ULTRA MONITOR 1.4 - MANAGER (JSON CONFIG EDITION)
# ==============================================================================

# --- Configuration ---
INSTALL_DIR="/opt/radar-sonar"
SERVICE_NAME="sonar-bot"
REPO_URL="https://github.com/Amirtn9/radar-sonar.git"
RAW_URL="https://raw.githubusercontent.com/Amirtn9/radar-sonar/main"
DB_FILE="sonar_ultra_pro.db"
KEY_FILE="secret.key"
CONFIG_FILE="sonar_config.json"

# --- Colors (Neon Theme) ---
RESET='\033[0m'
BOLD='\033[1m'
CYAN='\033[0;36m'
BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
PURPLE='\033[0;35m'

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
    echo -e "   ${CYAN}${BOLD}🦇 SONAR RADAR ULTRA MONITOR 1.4${RESET}"
    echo -e "   ${BLUE}──────────────────────────────────${RESET}"
    echo ""
}

function print_success() { echo -e "${GREEN}${BOLD}✅ $1${RESET}"; }
function print_error() { echo -e "${RED}${BOLD}❌ $1${RESET}"; }
function print_info() { echo -e "${YELLOW}➤ $1...${RESET}"; }
function wait_enter() { echo ""; read -p "Press [Enter] to continue..." dummy; }

# --- Helper: Read JSON with Python ---
function read_json_val() {
    local file=$1
    local key=$2
    if [ -f "$file" ]; then
        python3 -c "import json; print(json.load(open('$file')).get('$key', ''))" 2>/dev/null
    else
        echo ""
    fi
}

# --- Loading Animations ---
function show_loading() {
    local pid=$1
    local text=$2
    local spinstr='|/-\'
    while [ "$(ps a | awk '{print $1}' | grep $pid)" ]; do
        local temp=${spinstr#?}
        printf " [%c]  %s" "$spinstr" "$text"
        local spinstr=$temp${spinstr%"$temp"}
        sleep 0.1
        printf "\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b"
    done
    printf "    \b\b\b\b"
}

function progress_bar() {
    local duration=$1
    local width=30
    local step_time=$(echo "$duration / $width" | bc -l)
    echo -ne "\n"
    for ((i=0; i<=$width; i++)); do
        local percent=$((i * 100 / width))
        local filled=$(printf "%0.s█" $(seq 1 $i))
        local unfilled=$(printf "%0.s░" $(seq 1 $((width - i))))
        if [ $percent -lt 30 ]; then color=$RED; elif [ $percent -lt 70 ]; then color=$YELLOW; else color=$GREEN; fi
        printf "\r ${color}[${filled}${unfilled}]${RESET} ${percent}%%  Loading..."
        sleep $step_time
    done
    echo -ne "\n"
}

# --- Root Check ---
if [ "$EUID" -ne 0 ]; then echo -e "${RED}❌ Please run as root.${RESET}"; exit 1; fi

# ==============================================================================
# 🔧 CORE INSTALLATION LOGIC
# ==============================================================================

function install_process() {
    local KEEP_CONFIG=$1 # true = update mode, false = fresh install
    
    print_title
    echo -e "${BOLD}🚀 STARTING OPERATION...${RESET}\n"

    # 1. Stop Service
    if systemctl is-active --quiet $SERVICE_NAME; then
        print_info "Stopping active service"
        systemctl stop $SERVICE_NAME
    fi

    # 2. Backup Critical Data (DB & Config)
    local OLD_TOKEN=""
    local OLD_ADMIN=""
    
    print_info "Backing up Database & Keys"
    if [ -f "$INSTALL_DIR/$DB_FILE" ]; then cp "$INSTALL_DIR/$DB_FILE" /tmp/sonar_db.bak; fi
    if [ -f "$INSTALL_DIR/$KEY_FILE" ]; then cp "$INSTALL_DIR/$KEY_FILE" /tmp/sonar_key.bak; fi
    
    # اگر آپدیت است، اطلاعات را از فایل JSON موجود می‌خوانیم
    if [ "$KEEP_CONFIG" = true ] && [ -f "$INSTALL_DIR/$CONFIG_FILE" ]; then
        print_info "Reading configuration from $CONFIG_FILE"
        OLD_TOKEN=$(read_json_val "$INSTALL_DIR/$CONFIG_FILE" "bot_token")
        OLD_ADMIN=$(read_json_val "$INSTALL_DIR/$CONFIG_FILE" "admin_id")
    fi

    # 3. NUKE EVERYTHING (Clean Slate)
    print_info "Wiping directory for fresh install"
    rm -rf "$INSTALL_DIR"
    mkdir -p "$INSTALL_DIR"

    # 4. System Dependencies
    print_info "Updating System Packages"
    apt-get update -y > /dev/null 2>&1 &
    show_loading $! "Apt Update..."
    
    apt-get install -y python3 python3-pip python3-venv git curl build-essential libssl-dev libffi-dev python3-dev > /dev/null 2>&1 &
    show_loading $! "Installing OS Deps..."

    # 5. Download Source
    print_info "Cloning Source Code"
    if ! git clone "$REPO_URL" "$INSTALL_DIR" > /dev/null 2>&1; then
        curl -s -o "$INSTALL_DIR/bot.py" "$RAW_URL/bot.py"
        curl -s -o "$INSTALL_DIR/requirements.txt" "$RAW_URL/requirements.txt"
    fi

    # 6. Restore Data
    print_info "Restoring Database & Keys"
    if [ -f "/tmp/sonar_db.bak" ]; then mv /tmp/sonar_db.bak "$INSTALL_DIR/$DB_FILE"; fi
    if [ -f "/tmp/sonar_key.bak" ]; then mv /tmp/sonar_key.bak "$INSTALL_DIR/$KEY_FILE"; fi

    # 7. Setup Python Environment
    print_info "Creating Virtual Environment"
    python3 -m venv "$INSTALL_DIR/venv"
    source "$INSTALL_DIR/venv/bin/activate"

    print_info "Installing Python Libraries"
    pip install --upgrade pip setuptools wheel > /dev/null 2>&1
    pip install "python-telegram-bot[job-queue]" paramiko cryptography jdatetime matplotlib requests > /dev/null 2>&1 &
    show_loading $! "Pip Install..."

    # 8. Setup Service
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

    # 9. Handle Configuration (Restore or Ask)
    if [ "$KEEP_CONFIG" = true ] && [ -n "$OLD_TOKEN" ]; then
        print_info "Restoring Config (Token & Admin ID)"
        echo "{\"bot_token\": \"$OLD_TOKEN\", \"admin_id\": \"$OLD_ADMIN\"}" > "$INSTALL_DIR/$CONFIG_FILE"
    else
        # Fresh install or config missing -> Ask User
        configure_token_interactive
    fi

    # 10. Launch
    print_info "Starting Bot Service"
    systemctl restart $SERVICE_NAME
    
    # Fake loading time for python startup
    progress_bar 5

    if systemctl is-active --quiet $SERVICE_NAME; then
        print_success "Bot is ONLINE and Ready! 🦇"
    else
        print_error "Bot failed to start. Check logs."
    fi
    wait_enter
}

function configure_token_interactive() {
    print_title
    echo -e "${BOLD}⚙️ SETUP CONFIGURATION${RESET}\n"
    echo -e "${CYAN}🤖 Enter Telegram Bot Token:${RESET}"
    read -p ">> " TOKEN_INPUT
    echo -e "\n${CYAN}👤 Enter Admin Numeric ID:${RESET}"
    read -p ">> " ADMIN_INPUT

    if [ -n "$TOKEN_INPUT" ] && [ -n "$ADMIN_INPUT" ]; then
        # Create the JSON config file
        echo "{\"bot_token\": \"$TOKEN_INPUT\", \"admin_id\": \"$ADMIN_INPUT\"}" > "$INSTALL_DIR/$CONFIG_FILE"
        print_success "Config saved to $CONFIG_FILE"
    else
        print_error "Invalid input. Config file not created."
    fi
}

function manual_config_menu() {
    if [ ! -d "$INSTALL_DIR" ]; then print_error "Bot not installed."; wait_enter; return; fi
    configure_token_interactive
    systemctl restart $SERVICE_NAME
    print_success "Bot Restarted with new config."
    wait_enter
}

function full_restart() {
    print_title
    echo -e "${BOLD}♻️ FULL RESTART${RESET}\n"
    systemctl stop $SERVICE_NAME
    print_info "Killing zombie processes"
    pkill -f "$INSTALL_DIR/bot.py" > /dev/null 2>&1
    sleep 1
    systemctl start $SERVICE_NAME
    progress_bar 5
    if systemctl is-active --quiet $SERVICE_NAME; then
        print_success "Restarted Successfully."
    else
        print_error "Failed."
    fi
    wait_enter
}

function view_logs() {
    clear
    echo -e "${GREEN}${BOLD}📜 LIVE LOGS (Ctrl+C to exit)${RESET}"
    journalctl -u $SERVICE_NAME -f -n 50
}

function uninstall_bot() {
    print_title
    echo -e "${RED}${BOLD}🗑️ UNINSTALL${RESET}\n"
    read -p "Delete EVERYTHING (DB, Logs, Config)? (y/n): " confirm
    if [[ "$confirm" == "y" || "$confirm" == "Y" ]]; then
        systemctl stop $SERVICE_NAME
        systemctl disable $SERVICE_NAME > /dev/null 2>&1
        rm -f /etc/systemd/system/$SERVICE_NAME.service
        systemctl daemon-reload
        rm -rf "$INSTALL_DIR"
        print_success "Deleted."
    fi
    wait_enter
}

# --- Main Menu Loop ---
while true; do
    print_title
    echo -e " ${GREEN}1)${RESET} 🚀 Install Bot (Fresh Install)"
    echo -e " ${GREEN}2)${RESET} 🔄 Update Bot (Clean Update - Keeps Data)"
    echo -e " ${GREEN}3)${RESET} ♻️  Restart Bot"
    echo -e " ${GREEN}4)${RESET} 📜 View Logs"
    echo -e " ${GREEN}5)${RESET} ⚙️  Change Token/Admin"
    echo -e " ${GREEN}6)${RESET} 🗑️  Uninstall"
    echo -e " ${RED}7) ❌ Exit${RESET}"
    echo ""
    read -p " Select [1-7]: " OPTION
    case $OPTION in
        1) install_process false ;; # Fresh install (Ask config)
        2) install_process true  ;; # Update (Keep config)
        3) full_restart ;;
        4) view_logs ;;
        5) manual_config_menu ;;
        6) uninstall_bot ;;
        7) clear; exit ;;
        *) echo "Invalid Option" ;;
    esac
done
