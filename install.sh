#!/bin/bash

# ==============================================================================
# 🦇 SONAR RADAR ULTRA MONITOR - PROFESSIONAL INSTALLER (Server/Update/Reset)
# - Keeps original menu/structure, but makes install 0->100 automated and stable.
# - PostgreSQL only (no sqlite)
# ==============================================================================

# --- Configuration ---
INSTALL_DIR="/opt/radar-sonar"
SERVICE_NAME="sonar-bot"
API_SERVICE_NAME="sonar-api"
AGENT_SERVICE_NAME="sonar-agent"

REPO_URL="https://github.com/Amirtn9/radar-sonar.git"
RAW_URL="https://raw.githubusercontent.com/Amirtn9/radar-sonar/main"

KEY_FILE="secret.key"
CONFIG_FILE="sonar_config.json"
SETTINGS_FILE="settings.py"
LOG_FILE="/var/log/sonar_install.log"

# PostgreSQL Defaults (match your code expectations if any)
DB_NAME="sonar_ultra_pro"
DB_USER="sonar_user"
DB_PASS="SonarPassword2025"

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
    echo -e "   ${CYAN}${BOLD}🦇 SONAR RADAR ULTRA MONITOR${RESET}"
    echo -e "   ${BLUE}──────────────────────────────────${RESET}"
    echo ""
}

function log_msg() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"; }

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

# --- Loading Animations ---
function show_loading() {
    local pid=$1
    local text=$2
    local spinstr='|/-\'
    echo -ne "   "
    while ps -p "$pid" >/dev/null 2>&1; do
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
    local step_time
    step_time=$(echo "$duration / $width" | bc -l 2>/dev/null || echo "0.05")
    echo -ne "\n"
    for ((i=0; i<=$width; i++)); do
        local percent=$((i * 100 / width))
        local filled=$(printf "%0.s█" $(seq 1 $i))
        local unfilled=$(printf "%0.s░" $(seq 1 $((width - i))))
        if [ $percent -lt 30 ]; then color=$RED; elif [ $percent -lt 70 ]; then color=$YELLOW; else color=$GREEN; fi
        printf "\r ${color}[${filled}${unfilled}]${RESET} ${percent}%%"
        sleep "$step_time"
    done
    echo -ne "\n\n"
}

# --- Root Check ---
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}❌ Error: This script must be run as root.${RESET}"
    exit 1
fi

mkdir -p "$(dirname "$LOG_FILE")" >/dev/null 2>&1 || true
touch "$LOG_FILE" >/dev/null 2>&1 || true

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
        sed -i "s/^SUPER_ADMIN_ID = .*/SUPER_ADMIN_ID = $admin_id/" "$settings_path" 2>/dev/null || true
        log_msg "Updated SUPER_ADMIN_ID in settings.py"
    else
        log_msg "WARNING: settings.py not found for update."
    fi
}

# --- Helper: Port check ---
function port_in_use() {
    local p="$1"
    ss -lnt 2>/dev/null | awk '{print $4}' | grep -qE ":${p}$"
}

function find_free_port() {
    local start="$1"
    local p="$start"
    for _ in $(seq 1 50); do
        if port_in_use "$p"; then
            p=$((p+1))
        else
            echo "$p"
            return 0
        fi
    done
    echo "$start"
}

# --- Helper: Safe backup & restore ---
function backup_install_dir() {
    if [ -d "$INSTALL_DIR" ]; then
        local ts
        ts="$(date +%F-%H%M%S)"
        local bak="${INSTALL_DIR}.bak.${ts}"
        print_info "Backing up existing installation to $bak"
        mv "$INSTALL_DIR" "$bak"
        echo "$bak"
        return 0
    fi
    echo ""
}

function restore_critical_files_from_backup() {
    local bak="$1"
    if [ -z "$bak" ] || [ ! -d "$bak" ]; then
        return 0
    fi

    # Restore KEY_FILE
    if [ -f "$bak/$KEY_FILE" ]; then
        cp -a "$bak/$KEY_FILE" "$INSTALL_DIR/$KEY_FILE" 2>/dev/null || true
        log_msg "Restored $KEY_FILE from backup."
    fi

    # Restore sonar_config.json (if user chose KEEP_CONFIG)
    # (Handled later with JSON restore logic)
}

# --- Helper: Download/Extract source ---
function ensure_clean_install_dir() {
    rm -rf "$INSTALL_DIR"
    mkdir -p "$INSTALL_DIR"
}

function install_system_deps() {
    print_info "Installing System Dependencies"
    apt-get update -y > /dev/null 2>&1 &
    show_loading $! "Updating repositories..."

    # Minimal but complete dependencies for venv + postgres + builds
    DEPS="python3 python3-pip python3-venv git curl unzip ca-certificates \
build-essential libssl-dev libffi-dev python3-dev \
postgresql postgresql-contrib libpq-dev bc ufw"
    apt-get install -y $DEPS > /dev/null 2>&1 &
    show_loading $! "Installing packages..."
}

function download_source_menu() {
    print_title
    echo -e "${BOLD}📦 SOURCE INSTALL METHOD${RESET}\n"
    echo "1) Local ZIP file (recommended)"
    echo "2) Git clone (repo)"
    echo "3) Raw download (fallback)"
    echo ""
    read -p "Select [1-3]: " SRC_OPT
    echo "$SRC_OPT"
}

function extract_zip_to_install_dir() {
    local zip_path="$1"
    if [ ! -f "$zip_path" ]; then
        print_error "ZIP not found: $zip_path"
        return 1
    fi
    local tmp
    tmp="$(mktemp -d)"
    unzip -o "$zip_path" -d "$tmp" >/dev/null 2>&1 || { rm -rf "$tmp"; print_error "Failed to unzip."; return 1; }

    if [ -d "$tmp/radar-sonar" ]; then
        rsync -a --delete "$tmp/radar-sonar/" "$INSTALL_DIR/" >/dev/null 2>&1
    else
        rsync -a --delete "$tmp/" "$INSTALL_DIR/" >/dev/null 2>&1
    fi
    rm -rf "$tmp"
    return 0
}

function git_clone_to_install_dir() {
    if ! git clone "$REPO_URL" "$INSTALL_DIR" > /dev/null 2>&1; then
        return 1
    fi
    return 0
}

function raw_download_to_install_dir() {
    local FILES=("bot.py" "core.py" "cronjobs.py" "database.py" "keyboard.py" "settings.py" "monitor_agent.py" \
"ws_client.py" "admin_panel.py" "server_stats.py" "scoring.py" "tunnel_logic.py" "requirements.txt" "alerts.py" \
"logger_setup.py" "topics.py" "bot_logic.py" "states.py" "dispatcher.py" "api_server.py")

    for file in "${FILES[@]}"; do
        curl -s -f -o "$INSTALL_DIR/$file" "$RAW_URL/$file" >/dev/null 2>&1 || {
            print_error "Failed to download: $file"
            return 1
        }
    done
    return 0
}

# --- Python venv & pip ---
function setup_venv_and_pip() {
    print_info "Setting up Python Virtual Environment (.venv)"
    python3 -m venv "$INSTALL_DIR/.venv" >/dev/null 2>&1 || { print_error "venv creation failed"; return 1; }
    source "$INSTALL_DIR/.venv/bin/activate" >/dev/null 2>&1 || { print_error "venv activate failed"; return 1; }

    print_info "Upgrading pip"
    pip install --upgrade pip setuptools wheel >/dev/null 2>&1 || true

    print_info "Installing Python Libraries (requirements.txt)"
    if [ -f "$INSTALL_DIR/requirements.txt" ]; then
        pip install -r "$INSTALL_DIR/requirements.txt" > /dev/null 2>&1 &
        show_loading $! "Pip installing modules..."
    else
        print_error "requirements.txt not found!"
    fi

    # Enforce critical packages (requests/psycopg2/ptb job-queue)
    print_info "Ensuring critical packages"
    pip install -U requests psycopg2-binary "python-telegram-bot[job-queue]==20.8" APScheduler tzlocal >/dev/null 2>&1 || true

    # Quick import healthcheck
    python -c "import requests; import telegram; import psycopg2; print('OK')" >/dev/null 2>&1 || {
        print_error "Python import healthcheck failed (requests/telegram/psycopg2)."
        return 1
    }

    deactivate >/dev/null 2>&1 || true
    return 0
}

# --- systemd service install ---
function write_service_file() {
    print_info "Configuring Systemd Service ($SERVICE_NAME)"

    # Wrapper with flock to prevent duplicate instance on same host
    cat > "$INSTALL_DIR/run_bot.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
APP_DIR="$INSTALL_DIR"
PY="\$APP_DIR/.venv/bin/python"
LOCK="/var/run/sonar-bot.lock"
exec /usr/bin/flock -n "\$LOCK" "\$PY" "\$APP_DIR/bot.py"
EOF
    chmod +x "$INSTALL_DIR/run_bot.sh" >/dev/null 2>&1 || true

    cat <<EOF > /etc/systemd/system/$SERVICE_NAME.service
[Unit]
Description=Sonar Radar Ultra Pro Bot
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/run_bot.sh
Restart=always
RestartSec=5
TimeoutStartSec=60
TimeoutStopSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload >/dev/null 2>&1
    systemctl enable $SERVICE_NAME > /dev/null 2>&1
}

# ==============================================================================
# 🔧 DATABASE CONFIGURATION (PostgreSQL Only)
# ==============================================================================
function setup_postgres() {
    print_info "Configuring PostgreSQL Database"

    systemctl start postgresql >/dev/null 2>&1 || true
    systemctl enable postgresql >/dev/null 2>&1 || true

    # Create user if not exists
    sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1 || \
    sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASS';" >/dev/null 2>&1

    # Create DB if not exists
    sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1 || \
    sudo -u postgres psql -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;" >/dev/null 2>&1

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
    echo -e "${GRAY}Database: ${DB_NAME} | User: ${DB_USER}${RESET}"
    echo ""
    read -p "Type 'RESET' to confirm: " confirm
    if [[ "$confirm" != "RESET" ]]; then
        print_info "Cancelled."
        wait_enter
        return
    fi

    systemctl start postgresql >/dev/null 2>&1 || true
    systemctl enable postgresql >/dev/null 2>&1 || true

    print_info "Stopping Bot Service"
    systemctl stop $SERVICE_NAME >/dev/null 2>&1 || true

    print_info "Terminating active DB connections"
    sudo -u postgres psql -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${DB_NAME}' AND pid <> pg_backend_pid();" >/dev/null 2>&1 || true

    print_info "Dropping Database"
    sudo -u postgres psql -c "DROP DATABASE IF EXISTS ${DB_NAME};" >/dev/null 2>&1 || true

    print_info "Recreating Database"
    setup_postgres

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

    # 1. Stop Service(s)
    if systemctl is-active --quiet $SERVICE_NAME; then
        print_info "Stopping active service"
        systemctl stop $SERVICE_NAME >/dev/null 2>&1 || true
    fi

    # 2. Backup Critical Data (Keys + Config JSON)
    local OLD_TOKEN=""
    local OLD_ADMIN=""
    local OLD_PORT="8080"
    local OLD_WS_POOL="5"
    local OLD_WS_PING_INTERVAL="20"
    local OLD_WS_PING_TIMEOUT="20"

    local BACKUP_DIR=""
    BACKUP_DIR="$(backup_install_dir)"

    if [ -n "$BACKUP_DIR" ] && [ -f "$BACKUP_DIR/$KEY_FILE" ]; then
        cp -a "$BACKUP_DIR/$KEY_FILE" /tmp/sonar_key.bak >/dev/null 2>&1 || true
    fi

    if [ "$KEEP_CONFIG" = true ] && [ -n "$BACKUP_DIR" ] && [ -f "$BACKUP_DIR/$CONFIG_FILE" ]; then
        print_info "Preserving Configuration"
        OLD_TOKEN=$(read_json_val "$BACKUP_DIR/$CONFIG_FILE" "bot_token")
        OLD_ADMIN=$(read_json_val "$BACKUP_DIR/$CONFIG_FILE" "admin_id")
        OLD_PORT=$(read_json_val "$BACKUP_DIR/$CONFIG_FILE" "agent_port")
        OLD_WS_POOL=$(read_json_val "$BACKUP_DIR/$CONFIG_FILE" "ws_pool_max")
        OLD_WS_PING_INTERVAL=$(read_json_val "$BACKUP_DIR/$CONFIG_FILE" "ws_ping_interval")
        OLD_WS_PING_TIMEOUT=$(read_json_val "$BACKUP_DIR/$CONFIG_FILE" "ws_ping_timeout")

        [ -z "$OLD_PORT" ] && OLD_PORT="8080"
        [ -z "$OLD_WS_POOL" ] && OLD_WS_POOL="5"
        [ -z "$OLD_WS_PING_INTERVAL" ] && OLD_WS_PING_INTERVAL="20"
        [ -z "$OLD_WS_PING_TIMEOUT" ] && OLD_WS_PING_TIMEOUT="20"
    fi

    # 3. Clean install dir (fresh)
    print_info "Preparing installation directory"
    ensure_clean_install_dir

    # 4. System Dependencies
    install_system_deps

    # Configure Database
    setup_postgres

    # 5. Download Source
    print_info "Downloading Source Code"
    SRC_OPT="$(download_source_menu)"

    if [ "$SRC_OPT" = "1" ]; then
        read -p "Enter local ZIP path (example: /opt/radar_sonar_pro_2.9.zip): " ZIP_PATH
        if ! extract_zip_to_install_dir "$ZIP_PATH"; then
            print_error "ZIP install failed."
            wait_enter
            return
        fi
        print_success "Source installed from ZIP."
    elif [ "$SRC_OPT" = "2" ]; then
        if ! git_clone_to_install_dir; then
            print_error "Git clone failed."
            wait_enter
            return
        fi
        print_success "Source installed from Git."
    else
        print_info "Raw download fallback..."
        if ! raw_download_to_install_dir; then
            print_error "Raw download failed."
            wait_enter
            return
        fi
        print_success "Source installed from RAW."
    fi

    # 6. Restore Keys
    if [ -f "/tmp/sonar_key.bak" ]; then
        print_info "Restoring Keys"
        mv /tmp/sonar_key.bak "$INSTALL_DIR/$KEY_FILE" >/dev/null 2>&1 || true
    fi

    # 7. Setup Python Environment
    if ! setup_venv_and_pip; then
        print_error "Python environment setup failed."
        wait_enter
        return
    fi

    # 8. Setup Service (systemd)
    write_service_file

    # 9. Handle Configuration
    if [ "$KEEP_CONFIG" = true ] && [ -n "$OLD_TOKEN" ]; then
        # Port check & suggestion if occupied
        local PORT_OK="$OLD_PORT"
        if port_in_use "$PORT_OK"; then
            local NEW_PORT
            NEW_PORT="$(find_free_port "$PORT_OK")"
            print_info "Port $PORT_OK is in use. Suggested free port: $NEW_PORT"
            PORT_OK="$NEW_PORT"
        fi

        print_info "Restoring previous configuration"
        echo "{\"bot_token\": \"$OLD_TOKEN\", \"admin_id\": \"$OLD_ADMIN\", \"agent_port\": $PORT_OK, \"ws_pool_max\": $OLD_WS_POOL, \"ws_ping_interval\": $OLD_WS_PING_INTERVAL, \"ws_ping_timeout\": $OLD_WS_PING_TIMEOUT}" > "$INSTALL_DIR/$CONFIG_FILE"
        update_settings_py "$OLD_ADMIN"
    else
        configure_token_interactive
    fi

    # 10. Launch
    print_info "Starting Bot Service"
    systemctl restart $SERVICE_NAME >/dev/null 2>&1 || true

    progress_bar 3

    if systemctl is-active --quiet $SERVICE_NAME; then
        print_success "Bot is ONLINE and Ready! 🦇"
        echo -e "   ${GRAY}Logs: journalctl -u $SERVICE_NAME -f${RESET}"
    else
        print_error "Bot failed to start."
        echo -e "${YELLOW}Check logs: journalctl -u $SERVICE_NAME -f${RESET}"
    fi

    # Health: ensure systemd ExecStart uses venv wrapper
    systemctl show -p ExecStart $SERVICE_NAME | grep -q "$INSTALL_DIR/run_bot.sh" >/dev/null 2>&1 || \
        warn_msg "Warning: ExecStart does not point to run_bot.sh"

    wait_enter
}

function warn_msg() {
    echo -e "${YELLOW}${BOLD}⚠️  $1${RESET}"
    log_msg "WARN: $1"
}

function configure_token_interactive() {
    print_title
    echo -e "${BOLD}⚙️  SETUP CONFIGURATION${RESET}\n"

    echo -e "${CYAN}🤖 Enter Telegram Bot Token:${RESET}"
    read -p ">> " TOKEN_INPUT

    echo -e "\n${CYAN}👤 Enter Admin Numeric ID:${RESET}"
    read -p ">> " ADMIN_INPUT

    echo -e "\n${CYAN}🔌 Enter Agent WebSocket Port (Default: 8080):${RESET}"
    read -p ">> " PORT_INPUT
    PORT_INPUT=${PORT_INPUT:-8080}

    # Suggest free port if in use
    if port_in_use "$PORT_INPUT"; then
        local NEW_PORT
        NEW_PORT="$(find_free_port "$PORT_INPUT")"
        echo -e "${YELLOW}Port $PORT_INPUT is in use. Suggested: $NEW_PORT${RESET}"
        read -p "Use suggested port $NEW_PORT? [Y/n]: " yn
        yn=${yn:-Y}
        if [[ "$yn" =~ ^[Yy]$ ]]; then
            PORT_INPUT="$NEW_PORT"
        fi
    fi

    if [ -n "$TOKEN_INPUT" ] && [ -n "$ADMIN_INPUT" ]; then
        echo "{\"bot_token\": \"$TOKEN_INPUT\", \"admin_id\": \"$ADMIN_INPUT\", \"agent_port\": $PORT_INPUT, \"ws_pool_max\": 5, \"ws_ping_interval\": 20, \"ws_ping_timeout\": 20}" > "$INSTALL_DIR/$CONFIG_FILE"
        update_settings_py "$ADMIN_INPUT"
        print_success "Configuration Saved! Agent Port: $PORT_INPUT"

        print_info "Opening port $PORT_INPUT in firewall (best-effort)..."
        ufw allow "$PORT_INPUT"/tcp >/dev/null 2>&1 || true
        iptables -I INPUT -p tcp --dport "$PORT_INPUT" -j ACCEPT >/dev/null 2>&1 || true
    else
        print_error "Invalid input. Configuration failed."
    fi
}

function manual_config_menu() {
    if [ ! -d "$INSTALL_DIR" ]; then print_error "Bot not installed."; wait_enter; return; fi
    configure_token_interactive
    systemctl restart $SERVICE_NAME >/dev/null 2>&1 || true
    print_success "Bot Restarted with new config."
    wait_enter
}

function full_restart() {
    print_title
    echo -e "${BOLD}♻️  FULL RESTART SEQUENCE${RESET}\n"
    systemctl stop $SERVICE_NAME >/dev/null 2>&1 || true
    print_info "Terminating residual processes"
    pkill -f "$INSTALL_DIR/bot.py" > /dev/null 2>&1 || true
    sleep 1
    systemctl start $SERVICE_NAME >/dev/null 2>&1 || true
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
    echo -e "${YELLOW}WARNING: This will delete the install directory and service unit!${RESET}"
    read -p "Are you sure? (Type 'yes' to confirm): " confirm
    if [[ "$confirm" == "yes" ]]; then
        print_info "Stopping services..."
        systemctl stop $SERVICE_NAME >/dev/null 2>&1 || true
        systemctl disable $SERVICE_NAME > /dev/null 2>&1 || true
        rm -f /etc/systemd/system/$SERVICE_NAME.service >/dev/null 2>&1 || true
        systemctl daemon-reload >/dev/null 2>&1 || true

        print_info "Removing files..."
        rm -rf "$INSTALL_DIR"

        print_success "Uninstallation Complete."
    else
        print_info "Cancelled."
    fi
    wait_enter
}

# Option 7: Fix DB / Dependencies (real fix, not apt-get install -f only)
function fix_db_and_dependencies() {
    print_title
    echo -e "${BOLD}🛠  FIX DATABASE / DEPENDENCIES${RESET}\n"

    install_system_deps
    setup_postgres

    if [ -d "$INSTALL_DIR" ]; then
        print_info "Ensuring venv + pip packages"
        setup_venv_and_pip >/dev/null 2>&1 || true
        write_service_file >/dev/null 2>&1 || true
        systemctl restart $SERVICE_NAME >/dev/null 2>&1 || true
    fi

    print_success "Fixes Applied."
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
        7) fix_db_and_dependencies ;;
        8) reset_postgres_database ;;
        9) clear; exit ;;
        *) echo "Invalid Option" ;;
    esac
done
