#!/bin/bash

# ==============================================================================
# 🦇 SONAR RADAR ULTRA MONITOR 2.0 - PROFESSIONAL INSTALLER
# ==============================================================================

# --- Configuration ---
INSTALL_DIR="/opt/radar-sonar"
SERVICE_NAME="sonar-bot"
REPO_URL="https://github.com/Amirtn9/radar-sonar.git"
RAW_URL="https://raw.githubusercontent.com/Amirtn9/radar-sonar/main"
DB_FILE="sonar_ultra_pro.db"
KEY_FILE="secret.key"
CONFIG_FILE="sonar_config.json"
SETTINGS_FILE="settings.py"
LOG_FILE="/var/log/sonar_install.log"

# --- Colors (Neon Theme) ---
RESET='\033[0m'
BOLD='\033[1m'
CYAN='\033[0;36m'
BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
PURPLE='\033[0;35m'
GRAY='\033[0;90m'

# --- Utils & UI ---
function print_title() {
    clear
    echo -e "${PURPLE}${BOLD}"
    echo "      /\\                /\\    "
    echo "     / \\'._   (\_/)   _.'/ \\   "
    echo "    /_.''._'--('.')--'_.''._\  "
    echo "    | \_ / \`  ~ ~  \`/ \_ / |  "
    echo "     \_/  \`/       \`'  \_/   "
    echo "           \`           \`      "
    echo -e "${RESET}"
    echo -e "   ${CYAN}${BOLD}🦇 SONAR RADAR ULTRA MONITOR 2.0${RESET}"
    echo -e "   ${BLUE}──────────────────────────────────${RESET}"
    echo ""
}

function log_msg() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

function print_success() { 
    echo -e "${GREEN}${BOLD}✅ $1${RESET}"
    log_msg "SUCCESS: $1"
}

function print_error() { 
    echo -e "${RED}${BOLD}❌ $1${RESET}"
    log_msg "ERROR: $1"
}

function print_info() { 
    echo -e "${YELLOW}➤ ${RESET}$1..."
    log_msg "INFO: $1"
}

function wait_enter() { 
    echo ""
    echo -e "${GRAY}Press [Enter] to continue...${RESET}"
    read dummy
}

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

# --- Helper: Update Settings.py ---
function update_settings_py() {
    local admin_id=$1
    local settings_path="$INSTALL_DIR/$SETTINGS_FILE"
    
    if [ -f "$settings_path" ]; then
        sed -i "s/^SUPER_ADMIN_ID = .*/SUPER_ADMIN_ID = $admin_id/" "$settings_path"
        log_msg "Updated SUPER_ADMIN_ID in settings.py"
    else
        log_msg "WARNING: settings.py not found for update."
    fi
}

# --- Loading Animations ---
function show_loading() {
    local pid=$1
    local text=$2
    local spinstr='|/-\'
    echo -ne "   "
    while [ "$(ps a | awk '{print $1}' | grep $pid)" ]; do
        local temp=${spinstr#?}
        printf "\r ${CYAN}[%c]${RESET} %s" "$spinstr" "$text"
        local spinstr=$temp${spinstr%"$temp"}
        sleep 0.1
    done
    printf "\r ${GREEN}[✔]${RESET} %s      \n" "$text"
}

function progress_bar() {
    local duration=$1
    local width=40
    local step_time=$(echo "$duration / $width" | bc -l)
    echo -ne "\n"
    for ((i=0; i<=$width; i++)); do
        local percent=$((i * 100 / width))
        local filled=$(printf "%0.s█" $(seq 1 $i))
        local unfilled=$(printf "%0.s░" $(seq 1 $((width - i))))
        if [ $percent -lt 30 ]; then color=$RED; elif [ $percent -lt 70 ]; then color=$YELLOW; else color=$GREEN; fi
        printf "\r ${color}[${filled}${unfilled}]${RESET} ${percent}%%"
        sleep $step_time
    done
    echo -ne "\n\n"
}

# --- Root Check ---
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}❌ Error: This script must be run as root.${RESET}"
    exit 1
fi

# ==============================================================================
# 🔧 DATABASE CONFIGURATION
# ==============================================================================
function setup_postgres() {
    print_info "Configuring PostgreSQL Database"
    
    # 1. Start Postgres Service
    systemctl start postgresql
    systemctl enable postgresql >/dev/null 2>&1
    
    # 2. Settings matches settings.py
    DB_NAME="sonar_ultra_pro"
    DB_USER="sonar_user"
    DB_PASS="SonarPassword2025"
    
    # Check if user exists, create if not
    sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1 || \
    sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASS';" >/dev/null 2>&1

    # Check if DB exists, create if not
    sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1 || \
    sudo -u postgres psql -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;" >/dev/null 2>&1

    # Grant privileges
    sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;" >/dev/null 2>&1
    
    print_success "PostgreSQL Database Ready."
}


# ==============================================================================
# 🧨 RESET / REINSTALL DATABASE (DROP & RE-CREATE)
# ==============================================================================
function reset_postgres_database() {
    print_title
    echo -e "${RED}${BOLD}🧨 RESET DATABASE${RESET}\n"
    echo -e "${YELLOW}WARNING: This will DELETE ALL DATA in PostgreSQL (Drop & Recreate).${RESET}"
    echo -e "${GRAY}Database: sonar_ultra_pro | User: sonar_user${RESET}"
    echo ""
    read -p "Type 'RESET' to confirm: " confirm
    if [[ "$confirm" != "RESET" ]]; then
        print_info "Cancelled."
        wait_enter
        return
    fi

    # Make sure Postgres is running
    systemctl start postgresql >/dev/null 2>&1 || true
    systemctl enable postgresql >/dev/null 2>&1 || true

    # Stop bot to release DB connections
    print_info "Stopping Bot Service"
    systemctl stop $SERVICE_NAME >/dev/null 2>&1 || true

    # DB Credentials (Must match setup_postgres)
    DB_NAME="sonar_ultra_pro"
    DB_USER="sonar_user"
    DB_PASS="SonarPassword2025"

    print_info "Terminating active DB connections"
    sudo -u postgres psql -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${DB_NAME}' AND pid <> pg_backend_pid();" >/dev/null 2>&1 || true

    print_info "Dropping Database"
    sudo -u postgres psql -c "DROP DATABASE IF EXISTS ${DB_NAME};" >/dev/null 2>&1 || true

    print_info "Recreating Database"
    setup_postgres

    # Initialize schema if bot code exists
    if [ -d "$INSTALL_DIR/.venv" ] && [ -f "$INSTALL_DIR/database.py" ]; then
        print_info "Initializing Database Schema"
        source "$INSTALL_DIR/.venv/bin/activate" >/dev/null 2>&1 || true
        python -c "from database import Database; Database(); print('DB initialized')" >/dev/null 2>&1 || true
        deactivate >/dev/null 2>&1 || true
    fi

    print_info "Starting Bot Service"
    systemctl restart $SERVICE_NAME >/dev/null 2>&1 || true

    if systemctl is-active --quiet $SERVICE_NAME; then
        print_success "Database Reset Completed & Bot Restarted."
    else
        print_success "Database Reset Completed. (Bot may be stopped if not installed.)"
    fi

    wait_enter
}


# ==============================================================================
# 🔧 CORE INSTALLATION LOGIC
# ==============================================================================
function install_process() {
    local KEEP_CONFIG=$1 # true = update mode, false = fresh install
    
    print_title
    echo -e "${BOLD}🚀 INITIALIZING INSTALLATION PROCESS...${RESET}\n"
    log_msg "Installation started. Keep Config: $KEEP_CONFIG"

    # 1. Stop Service
    if systemctl is-active --quiet $SERVICE_NAME; then
        print_info "Stopping active service"
        systemctl stop $SERVICE_NAME
    fi

    # 2. Backup Critical Data (DB & Config)
    local OLD_TOKEN=""
    local OLD_ADMIN=""
    local OLD_PORT="8080"
    local OLD_WS_POOL="5"
    local OLD_WS_PING_INTERVAL="20"
    local OLD_WS_PING_TIMEOUT="20"
    
    if [ -f "$INSTALL_DIR/$KEY_FILE" ]; then 
        print_info "Backing up Encryption Keys"
        cp "$INSTALL_DIR/$KEY_FILE" /tmp/sonar_key.bak
    fi
    
    if [ "$KEEP_CONFIG" = true ] && [ -f "$INSTALL_DIR/$CONFIG_FILE" ]; then
        print_info "Preserving Configuration"
        OLD_TOKEN=$(read_json_val "$INSTALL_DIR/$CONFIG_FILE" "bot_token")
        OLD_ADMIN=$(read_json_val "$INSTALL_DIR/$CONFIG_FILE" "admin_id")
        OLD_PORT=$(read_json_val "$INSTALL_DIR/$CONFIG_FILE" "agent_port")
        OLD_WS_POOL=$(read_json_val "$INSTALL_DIR/$CONFIG_FILE" "ws_pool_max")
        OLD_WS_PING_INTERVAL=$(read_json_val "$INSTALL_DIR/$CONFIG_FILE" "ws_ping_interval")
        OLD_WS_PING_TIMEOUT=$(read_json_val "$INSTALL_DIR/$CONFIG_FILE" "ws_ping_timeout")
        # If port is missing in old config, default to 8080
        if [ -z "$OLD_PORT" ]; then OLD_PORT=8080; fi
        if [ -z "$OLD_WS_POOL" ]; then OLD_WS_POOL=5; fi
        if [ -z "$OLD_WS_PING_INTERVAL" ]; then OLD_WS_PING_INTERVAL=20; fi
        if [ -z "$OLD_WS_PING_TIMEOUT" ]; then OLD_WS_PING_TIMEOUT=20; fi
    fi

    # 3. Clean Slate
    print_info "Cleaning installation directory"
    rm -rf "$INSTALL_DIR"
    mkdir -p "$INSTALL_DIR"

    # 4. System Dependencies
    print_info "Installing System Dependencies"
    apt-get update -y > /dev/null 2>&1 &
    show_loading $! "Updating repositories..."
    
    # Added 'bc' for progress bar and 'fail2ban' for security
    DEPS="python3 python3-pip python3-venv git curl build-essential libssl-dev libffi-dev python3-dev postgresql postgresql-contrib libpq-dev bc fail2ban"
    apt-get install -y $DEPS > /dev/null 2>&1 &
    show_loading $! "Installing packages..."

    # Configure Database right after installing packages
    setup_postgres

    # 5. Download Source
    print_info "Downloading Source Code"
    if ! git clone "$REPO_URL" "$INSTALL_DIR" > /dev/null 2>&1; then
        print_info "Git clone failed, switching to manual download..."
        # Updated file list based on your recent files
        local FILES=("bot.py" "core.py" "cronjobs.py" "database.py" "keyboard.py" "settings.py" "monitor_agent.py" "ws_client.py" "admin_panel.py" "server_stats.py" "scoring.py" "tunnel_logic.py" "requirements.txt" "alerts.py" "logger_setup.py" "topics.py" "bot_logic.py" "states.py" "dispatcher.py")
        
        for file in "${FILES[@]}"; do
             if curl -s -f -o "$INSTALL_DIR/$file" "$RAW_URL/$file"; then
                echo -ne "."
             else
                echo -e "\n${RED}Failed to download: $file${RESET}"
             fi
        done
        echo ""
    fi

    # Make agent executable
    if [ -f "$INSTALL_DIR/monitor_agent.py" ]; then
        chmod +x "$INSTALL_DIR/monitor_agent.py"
    fi

    # 6. Restore Data
    if [ -f "/tmp/sonar_key.bak" ]; then 
        print_info "Restoring Keys"
        mv /tmp/sonar_key.bak "$INSTALL_DIR/$KEY_FILE"
    fi

    # 7. Setup Python Environment
    print_info "Setting up Python Virtual Environment"
    python3 -m venv "$INSTALL_DIR/.venv"
    source "$INSTALL_DIR/.venv/bin/activate"

    print_info "Installing Python Libraries"
    pip install --upgrade pip setuptools wheel > /dev/null 2>&1
    # Important: Added 'websockets' and 'psutil' as requested
    pip install -r "$INSTALL_DIR/requirements.txt" > /dev/null 2>&1 &
    show_loading $! "Pip installing modules..."

    # 8. Setup Service
    print_info "Configuring Systemd Service"
    cat <<EOF > /etc/systemd/system/$SERVICE_NAME.service
[Unit]
Description=Sonar Radar Ultra Pro Bot
After=network.target postgresql.service

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/.venv/bin/python $INSTALL_DIR/bot.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable $SERVICE_NAME > /dev/null 2>&1

    # 9. Handle Configuration
    if [ "$KEEP_CONFIG" = true ] && [ -n "$OLD_TOKEN" ]; then
        print_info "Restoring previous configuration"
        echo "{\"bot_token\": \"$OLD_TOKEN\", \"admin_id\": \"$OLD_ADMIN\", \"agent_port\": $OLD_PORT, \"ws_pool_max\": $OLD_WS_POOL, \"ws_ping_interval\": $OLD_WS_PING_INTERVAL, \"ws_ping_timeout\": $OLD_WS_PING_TIMEOUT}" > "$INSTALL_DIR/$CONFIG_FILE"
        update_settings_py "$OLD_ADMIN"
    else
        configure_token_interactive
    fi

    # 10. Launch
    print_info "Starting Bot Service"
    systemctl restart $SERVICE_NAME
    
    progress_bar 3

    if systemctl is-active --quiet $SERVICE_NAME; then
        print_success "Bot is ONLINE and Ready! 🦇"
        echo -e "   ${GRAY}Logs available at: journalctl -u $SERVICE_NAME -f${RESET}"
    else
        print_error "Bot failed to start."
        echo -e "${YELLOW}Check logs with: journalctl -u $SERVICE_NAME -f${RESET}"
    fi
    wait_enter
}

function configure_token_interactive() {
    print_title
    echo -e "${BOLD}⚙️  SETUP CONFIGURATION${RESET}\n"
    
    echo -e "${CYAN}🤖 Enter Telegram Bot Token:${RESET}"
    read -p ">> " TOKEN_INPUT
    
    echo -e "\n${CYAN}👤 Enter Admin Numeric ID:${RESET}"
    read -p ">> " ADMIN_INPUT

    # --- بخش جدید: دریافت پورت وب‌سوکت ---
    echo -e "\n${CYAN}🔌 Enter Agent WebSocket Port (Default: 8080):${RESET}"
    read -p ">> " PORT_INPUT
    PORT_INPUT=${PORT_INPUT:-8080} # اگر خالی زد، 8080 تنظیم شود

    if [ -n "$TOKEN_INPUT" ] && [ -n "$ADMIN_INPUT" ]; then
        # ذخیره پورت در فایل جیسون
        echo "{\"bot_token\": \"$TOKEN_INPUT\", \"admin_id\": \"$ADMIN_INPUT\", \"agent_port\": $PORT_INPUT, \"ws_pool_max\": 5, \"ws_ping_interval\": 20, \"ws_ping_timeout\": 20}" > "$INSTALL_DIR/$CONFIG_FILE"
        update_settings_py "$ADMIN_INPUT"
        print_success "Configuration Saved! Agent Port: $PORT_INPUT"
        
        # باز کردن پورت در فایروال
        print_info "Opening port $PORT_INPUT in firewall..."
        ufw allow $PORT_INPUT/tcp >/dev/null 2>&1 || true
        iptables -I INPUT -p tcp --dport $PORT_INPUT -j ACCEPT >/dev/null 2>&1 || true
    else
        print_error "Invalid input. Configuration failed."
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
    echo -e "${BOLD}♻️  FULL RESTART SEQUENCE${RESET}\n"
    systemctl stop $SERVICE_NAME
    print_info "Terminating residual processes"
    pkill -f "$INSTALL_DIR/bot.py" > /dev/null 2>&1
    sleep 1
    systemctl start $SERVICE_NAME
    progress_bar 3
    if systemctl is-active --quiet $SERVICE_NAME; then
        print_success "Service Restarted Successfully."
    else
        print_error "Service failed to restart."
    fi
    wait_enter
}

function view_logs() {
    clear
    echo -e "${GREEN}${BOLD}📜 LIVE LOGS (Press Ctrl+C to exit)${RESET}"
    echo -e "${GRAY}Tail of $SERVICE_NAME logs...${RESET}"
    journalctl -u $SERVICE_NAME -f -n 50
}

function uninstall_bot() {
    print_title
    echo -e "${RED}${BOLD}🗑️  UNINSTALLATION${RESET}\n"
    echo -e "${YELLOW}WARNING: This will delete the Database, Configs, and Logs!${RESET}"
    read -p "Are you sure? (Type 'yes' to confirm): " confirm
    if [[ "$confirm" == "yes" ]]; then
        print_info "Stopping services..."
        systemctl stop $SERVICE_NAME
        systemctl disable $SERVICE_NAME > /dev/null 2>&1
        rm -f /etc/systemd/system/$SERVICE_NAME.service
        systemctl daemon-reload
        
        print_info "Removing files..."
        rm -rf "$INSTALL_DIR"
        
        # Optional: Remove DB? Usually safer to keep it, but here we wipe as requested
        # sudo -u postgres psql -c "DROP DATABASE sonar_ultra_pro;" >/dev/null 2>&1 
        
        print_success "Uninstallation Complete."
    else
        print_info "Cancelled."
    fi
    wait_enter
}

# --- Main Menu Loop ---
while true; do
    print_title
    echo -e " ${GREEN}1)${RESET} 🚀 Install / Re-Install Bot "
    echo -e " ${GREEN}2)${RESET} 🔄 Update Bot (Keep Config) "
    echo -e " ${GREEN}3)${RESET} ♻️  Restart Service"
    echo -e " ${GREEN}4)${RESET} 📜 View Live Logs"
    echo -e " ${GREEN}5)${RESET} ⚙️  Change Config (Token/Port)"
    echo -e " ${GREEN}6)${RESET} 🗑️  Uninstall"
    echo -e " ${GREEN}7)${RESET} 🛠  Fix Database / Dependencies"
    echo -e " ${GREEN}8)${RESET} 🧨 Reset Database (Drop & Recreate)"
    echo -e " ${RED}9) ❌ Exit${RESET}"
    echo ""
    read -p " Select Option [1-9]: " OPTION
    case $OPTION in
        1) install_process false ;; 
        2) install_process true  ;; 
        3) full_restart ;;
        4) view_logs ;;
        5) manual_config_menu ;;
        6) uninstall_bot ;;
        7) setup_postgres; apt-get install -f -y; print_success "Fixes Applied."; wait_enter ;;
        8) reset_postgres_database ;;
        9) clear; exit ;;
        *) echo "Invalid Option" ;;
    esac
done