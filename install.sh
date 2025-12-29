#!/bin/bash
set -Eeuo pipefail

# ==============================================================================
# 🦇 SONAR RADAR ULTRA MONITOR - PROFESSIONAL INSTALLER (GitHub Only)
# Repo: https://github.com/Amirtn9/Radar-Sonar
# - 0->100 automated
# - PostgreSQL only
# - Always uses /opt/radar-sonar/.venv for systemd ExecStart
# ==============================================================================

# --- Configuration ---
INSTALL_DIR="/opt/radar-sonar"
SERVICE_NAME="sonar-bot"
API_SERVICE_NAME="sonar-api"
AGENT_SERVICE_NAME="sonar-agent"

REPO_URL="https://github.com/Amirtn9/Radar-Sonar.git"
REPO_BRANCH="main"

KEY_FILE="secret.key"
CONFIG_FILE="sonar_config.json"
SETTINGS_FILE="settings.py"
LOG_FILE="/var/log/sonar_install.log"

# PostgreSQL Defaults
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

# --- Root Check ---
if [ "${EUID}" -ne 0 ]; then
  echo -e "${RED}❌ Error: This script must be run as root.${RESET}"
  exit 1
fi

mkdir -p "$(dirname "$LOG_FILE")" >/dev/null 2>&1 || true
touch "$LOG_FILE" >/dev/null 2>&1 || true

function log_msg() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"; }

function print_title() {
  clear
  echo -e "${PURPLE}${BOLD}"
  echo "      /\\                /\\    "
  echo "     / \\'._   (\\_/)   _.'/ \\   "
  echo "    /_.''._'--('.')--'_.''._\\  "
  echo "    | \\_ / \\`  ~ ~  \\`/ \\_ / |  "
  echo "     \\_/  \\`/       \\`'  \\_/   "
  echo "           \\`           \\`      "
  echo -e "${RESET}"
  echo -e "   ${CYAN}${BOLD}🦇 SONAR RADAR ULTRA MONITOR${RESET}"
  echo -e "   ${BLUE}──────────────────────────────────${RESET}"
  echo ""
}

function print_success() { echo -e "${GREEN}${BOLD}✅ $1${RESET}"; log_msg "SUCCESS: $1"; }
function print_error()   { echo -e "${RED}${BOLD}❌ $1${RESET}"; log_msg "ERROR: $1"; }
function print_info()    { echo -e "${YELLOW}➤ ${RESET}$1..."; log_msg "INFO: $1"; }
function warn_msg()      { echo -e "${YELLOW}${BOLD}⚠️  $1${RESET}"; log_msg "WARN: $1"; }

function wait_enter() {
  echo ""
  echo -e "${GRAY}Press [Enter] to continue...${RESET}"
  read -r dummy || true
}

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
    local filled unfilled color
    filled=$(printf "%0.s█" $(seq 1 $i))
    unfilled=$(printf "%0.s░" $(seq 1 $((width - i))))
    if [ $percent -lt 30 ]; then color=$RED; elif [ $percent -lt 70 ]; then color=$YELLOW; else color=$GREEN; fi
    printf "\r ${color}[${filled}${unfilled}]${RESET} ${percent}%%"
    sleep "$step_time"
  done
  echo -ne "\n\n"
}

function read_json_val() {
  local file=$1 key=$2
  if [ -f "$file" ]; then
    python3 -c "import json; print(json.load(open('$file')).get('$key',''))" 2>/dev/null || true
  else
    echo ""
  fi
}

function update_settings_py() {
  local admin_id=$1
  local settings_path="$INSTALL_DIR/$SETTINGS_FILE"
  if [ -f "$settings_path" ]; then
    sed -i "s/^SUPER_ADMIN_ID = .*/SUPER_ADMIN_ID = $admin_id/" "$settings_path" 2>/dev/null || true
    log_msg "Updated SUPER_ADMIN_ID in settings.py"
  else
    warn_msg "settings.py not found for update (skipped)."
  fi
}

function port_in_use() { ss -lnt 2>/dev/null | awk '{print $4}' | grep -qE ":${1}$"; }

function find_free_port() {
  local start="$1"
  local p="$start"
  for _ in $(seq 1 80); do
    if port_in_use "$p"; then p=$((p+1)); else echo "$p"; return 0; fi
  done
  echo "$start"
}

function install_system_deps() {
  print_info "Installing System Dependencies"
  apt-get update -y >/dev/null 2>&1 &
  show_loading $! "Updating repositories..."
  # NOTE: rsync for safe copy, ufw for firewall, lsof/ss tools exist in iproute2
  local DEPS="python3 python3-pip python3-venv git curl ca-certificates rsync unzip \
build-essential libssl-dev libffi-dev python3-dev \
postgresql postgresql-contrib libpq-dev bc ufw iproute2"
  apt-get install -y $DEPS >/dev/null 2>&1 &
  show_loading $! "Installing packages..."
}

function setup_postgres() {
  print_info "Configuring PostgreSQL Database"
  systemctl start postgresql >/dev/null 2>&1 || true
  systemctl enable postgresql >/dev/null 2>&1 || true

  # Avoid “could not change directory” by running from /
  ( cd / || true
    sudo -u postgres psql -d postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" | grep -q 1 || \
      sudo -u postgres psql -d postgres -c "CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASS}';" >/dev/null 2>&1

    sudo -u postgres psql -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1 || \
      sudo -u postgres psql -d postgres -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};" >/dev/null 2>&1

    sudo -u postgres psql -d postgres -c "GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};" >/dev/null 2>&1
  ) || true

  print_success "PostgreSQL Database Ready."
}

function backup_install_dir() {
  if [ -d "$INSTALL_DIR" ]; then
    local ts bak
    ts="$(date +%F-%H%M%S)"
    bak="${INSTALL_DIR}.bak.${ts}"
    print_info "Backing up existing installation to $bak"
    mv "$INSTALL_DIR" "$bak"
    echo "$bak"
  else
    echo ""
  fi
}

function ensure_clean_install_dir() {
  rm -rf "$INSTALL_DIR"
  mkdir -p "$INSTALL_DIR"
}

function clone_repo_to_install_dir() {
  print_info "Cloning from GitHub (${REPO_URL})"
  git clone --depth 1 --branch "$REPO_BRANCH" "$REPO_URL" "$INSTALL_DIR" >/dev/null 2>&1 || return 1
  return 0
}

function verify_repo_files() {
  if [ ! -f "$INSTALL_DIR/bot.py" ]; then
    print_error "bot.py not found in $INSTALL_DIR (clone looks incomplete)."
    ls -lah "$INSTALL_DIR" || true
    return 1
  fi
  if [ ! -f "$INSTALL_DIR/requirements.txt" ]; then
    print_error "requirements.txt not found in $INSTALL_DIR."
    ls -lah "$INSTALL_DIR" || true
    return 1
  fi
  return 0
}

function setup_venv_and_pip() {
  print_info "Setting up Python Virtual Environment (.venv)"
  rm -rf "$INSTALL_DIR/.venv" >/dev/null 2>&1 || true
  python3 -m venv "$INSTALL_DIR/.venv" >/dev/null 2>&1 || { print_error "venv creation failed"; return 1; }

  # shellcheck disable=SC1091
  source "$INSTALL_DIR/.venv/bin/activate" >/dev/null 2>&1 || { print_error "venv activate failed"; return 1; }

  print_info "Upgrading pip"
  pip install --upgrade pip setuptools wheel >/dev/null 2>&1 || true

  print_info "Installing Python Libraries (requirements.txt)"
  pip install -r "$INSTALL_DIR/requirements.txt" >/dev/null 2>&1 &
  show_loading $! "Pip installing modules..."

  # Ensure critical packages (prevents JobQueue + requests/psycopg2 missing)
  print_info "Ensuring critical packages"
  pip install -U requests psycopg2-binary "python-telegram-bot[job-queue]" websockets psutil APScheduler tzlocal >/dev/null 2>&1 || true

  python -c "import requests, psycopg2; import telegram; print('OK')" >/dev/null 2>&1 || {
    print_error "Python import healthcheck failed (requests/telegram/psycopg2)."
    deactivate >/dev/null 2>&1 || true
    return 1
  }

  deactivate >/dev/null 2>&1 || true
  return 0
}

function write_service_file() {
  print_info "Configuring Systemd Service ($SERVICE_NAME)"

  cat > "$INSTALL_DIR/run_bot.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
APP_DIR="$INSTALL_DIR"
PY="\$APP_DIR/.venv/bin/python"
LOCK="/var/run/sonar-bot.lock"
export PYTHONUNBUFFERED=1
exec /usr/bin/flock -n "\$LOCK" "\$PY" "\$APP_DIR/bot.py"
EOF
  chmod +x "$INSTALL_DIR/run_bot.sh" >/dev/null 2>&1 || true

  cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=Sonar Radar Bot
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
  systemctl enable "$SERVICE_NAME" >/dev/null 2>&1
}

function configure_token_interactive() {
  print_title
  echo -e "${BOLD}⚙️  SETUP CONFIGURATION${RESET}\n"

  echo -e "${CYAN}🤖 Enter Telegram Bot Token:${RESET}"
  read -r -p ">> " TOKEN_INPUT

  echo -e "\n${CYAN}👤 Enter Admin Numeric ID:${RESET}"
  read -r -p ">> " ADMIN_INPUT

  echo -e "\n${CYAN}🔌 Enter Agent WebSocket Port (Default: 8080):${RESET}"
  read -r -p ">> " PORT_INPUT
  PORT_INPUT=${PORT_INPUT:-8080}

  if port_in_use "$PORT_INPUT"; then
    local NEW_PORT
    NEW_PORT="$(find_free_port "$PORT_INPUT")"
    echo -e "${YELLOW}Port $PORT_INPUT is in use. Suggested: $NEW_PORT${RESET}"
    read -r -p "Use suggested port $NEW_PORT? [Y/n]: " yn
    yn=${yn:-Y}
    if [[ "$yn" =~ ^[Yy]$ ]]; then
      PORT_INPUT="$NEW_PORT"
    fi
  fi

  if [ -n "${TOKEN_INPUT:-}" ] && [ -n "${ADMIN_INPUT:-}" ]; then
    echo "{\"bot_token\":\"$TOKEN_INPUT\",\"admin_id\":\"$ADMIN_INPUT\",\"agent_port\":$PORT_INPUT,\"ws_pool_max\":5,\"ws_ping_interval\":20,\"ws_ping_timeout\":20}" > "$INSTALL_DIR/$CONFIG_FILE"
    update_settings_py "$ADMIN_INPUT"
    print_success "Configuration Saved! Agent Port: $PORT_INPUT"

    print_info "Opening port $PORT_INPUT in firewall (best-effort)"
    ufw allow "${PORT_INPUT}/tcp" >/dev/null 2>&1 || true
    iptables -I INPUT -p tcp --dport "$PORT_INPUT" -j ACCEPT >/dev/null 2>&1 || true
  else
    print_error "Invalid input. Configuration failed."
  fi
}

function install_process() {
  local KEEP_CONFIG=$1

  print_title
  echo -e "${BOLD}🚀 INITIALIZING INSTALLATION PROCESS...${RESET}\n"
  log_msg "Installation started. Keep Config: $KEEP_CONFIG"

  # Stop service first
  if systemctl is-active --quiet "$SERVICE_NAME"; then
    print_info "Stopping active service"
    systemctl stop "$SERVICE_NAME" >/dev/null 2>&1 || true
  fi

  # Backup keys + config
  local OLD_TOKEN="" OLD_ADMIN="" OLD_PORT="8080" OLD_WS_POOL="5" OLD_WS_PING_INTERVAL="20" OLD_WS_PING_TIMEOUT="20"
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

  # Fresh dir
  print_info "Preparing installation directory"
  ensure_clean_install_dir

  # Deps + DB
  install_system_deps
  setup_postgres

  # GitHub only
  print_info "Downloading Source Code (GitHub)"
  if ! clone_repo_to_install_dir; then
    print_error "Git clone failed. Check network/DNS/GitHub access."
    wait_enter
    return
  fi
  print_success "Source installed from GitHub."

  if ! verify_repo_files; then
    wait_enter
    return
  fi

  # Restore key
  if [ -f "/tmp/sonar_key.bak" ]; then
    print_info "Restoring Keys"
    mv /tmp/sonar_key.bak "$INSTALL_DIR/$KEY_FILE" >/dev/null 2>&1 || true
  fi

  # venv + pip
  if ! setup_venv_and_pip; then
    print_error "Python environment setup failed."
    wait_enter
    return
  fi

  # systemd
  write_service_file

  # config
  if [ "$KEEP_CONFIG" = true ] && [ -n "${OLD_TOKEN:-}" ]; then
    local PORT_OK="$OLD_PORT"
    if port_in_use "$PORT_OK"; then
      local NEW_PORT
      NEW_PORT="$(find_free_port "$PORT_OK")"
      warn_msg "Port $PORT_OK is in use. Using $NEW_PORT"
      PORT_OK="$NEW_PORT"
    fi

    print_info "Restoring previous configuration"
    echo "{\"bot_token\":\"$OLD_TOKEN\",\"admin_id\":\"$OLD_ADMIN\",\"agent_port\":$PORT_OK,\"ws_pool_max\":$OLD_WS_POOL,\"ws_ping_interval\":$OLD_WS_PING_INTERVAL,\"ws_ping_timeout\":$OLD_WS_PING_TIMEOUT}" > "$INSTALL_DIR/$CONFIG_FILE"
    update_settings_py "$OLD_ADMIN"
  else
    configure_token_interactive
  fi

  # start
  print_info "Starting Bot Service"
  systemctl restart "$SERVICE_NAME" >/dev/null 2>&1 || true
  progress_bar 2

  # verify ExecStart points to venv wrapper
  local ES
  ES="$(systemctl show -p ExecStart "$SERVICE_NAME" | tr -d '\n' || true)"
  if echo "$ES" | grep -q "$INSTALL_DIR/run_bot.sh"; then
    print_success "Service ExecStart OK (run_bot.sh)."
  else
    warn_msg "ExecStart is not run_bot.sh. Your unit may be overwritten elsewhere!"
    echo "$ES"
  fi

  if systemctl is-active --quiet "$SERVICE_NAME"; then
    print_success "Bot is ONLINE and Ready! 🦇"
    echo -e "   ${GRAY}Logs: journalctl -u $SERVICE_NAME -f${RESET}"
  else
    print_error "Bot failed to start."
    echo -e "${YELLOW}Check logs: journalctl -u $SERVICE_NAME -n 200 --no-pager${RESET}"
  fi

  wait_enter
}

function reset_postgres_database() {
  print_title
  echo -e "${RED}${BOLD}🧨 RESET DATABASE${RESET}\n"
  echo -e "${YELLOW}WARNING: This will DELETE ALL DATA in PostgreSQL (Drop & Recreate).${RESET}"
  echo -e "${GRAY}Database: ${DB_NAME} | User: ${DB_USER}${RESET}"
  echo ""
  read -r -p "Type 'RESET' to confirm: " confirm
  if [[ "$confirm" != "RESET" ]]; then
    print_info "Cancelled."
    wait_enter
    return
  fi

  systemctl start postgresql >/dev/null 2>&1 || true

  print_info "Stopping Bot Service"
  systemctl stop "$SERVICE_NAME" >/dev/null 2>&1 || true

  print_info "Terminating active DB connections"
  sudo -u postgres psql -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${DB_NAME}' AND pid <> pg_backend_pid();" >/dev/null 2>&1 || true

  print_info "Dropping Database"
  sudo -u postgres psql -d postgres -c "DROP DATABASE IF EXISTS ${DB_NAME};" >/dev/null 2>&1 || true

  print_info "Recreating Database"
  setup_postgres

  print_info "Starting Bot Service"
  systemctl restart "$SERVICE_NAME" >/dev/null 2>&1 || true

  print_success "Database Reset Completed."
  wait_enter
}

function fix_db_and_dependencies() {
  print_title
  echo -e "${BOLD}🛠  FIX DATABASE / DEPENDENCIES${RESET}\n"

  install_system_deps
  setup_postgres

  if [ -d "$INSTALL_DIR" ]; then
    print_info "Rebuilding venv + pip packages"
    setup_venv_and_pip >/dev/null 2>&1 || true
    write_service_file >/dev/null 2>&1 || true
    systemctl restart "$SERVICE_NAME" >/dev/null 2>&1 || true
  fi

  print_success "Fixes Applied."
  wait_enter
}

function full_restart() {
  print_title
  echo -e "${BOLD}♻️  FULL RESTART SEQUENCE${RESET}\n"
  systemctl stop "$SERVICE_NAME" >/dev/null 2>&1 || true
  print_info "Terminating residual processes"
  pkill -f "$INSTALL_DIR/bot.py" >/dev/null 2>&1 || true
  sleep 1
  systemctl start "$SERVICE_NAME" >/dev/null 2>&1 || true
  progress_bar 2
  systemctl is-active --quiet "$SERVICE_NAME" && print_success "Service Restarted Successfully." || print_error "Service failed to restart."
  wait_enter
}

function view_logs() {
  clear
  echo -e "${GREEN}${BOLD}📜 LIVE LOGS (Press Ctrl+C to exit)${RESET}"
  echo ""
  echo "1) bot"
  echo "2) api"
  echo "3) agent"
  echo "4) postgres"
  echo ""
  read -r -p "Select log [1-4]: " LOPT
  case "$LOPT" in
    1) journalctl -u "$SERVICE_NAME" -f -n 80 ;;
    2) journalctl -u "$API_SERVICE_NAME" -f -n 80 || { echo "api service not found"; sleep 2; } ;;
    3) journalctl -u "$AGENT_SERVICE_NAME" -f -n 80 || { echo "agent service not found"; sleep 2; } ;;
    4) journalctl -u postgresql -f -n 120 ;;
    *) echo "Invalid"; sleep 1 ;;
  esac
}

function manual_config_menu() {
  if [ ! -d "$INSTALL_DIR" ]; then print_error "Bot not installed."; wait_enter; return; fi
  configure_token_interactive
  systemctl restart "$SERVICE_NAME" >/dev/null 2>&1 || true
  print_success "Bot Restarted with new config."
  wait_enter
}

function uninstall_bot() {
  print_title
  echo -e "${RED}${BOLD}🗑️  UNINSTALLATION${RESET}\n"
  echo -e "${YELLOW}WARNING: This will delete the install directory and service unit!${RESET}"
  read -r -p "Are you sure? (Type 'yes' to confirm): " confirm
  if [[ "$confirm" == "yes" ]]; then
    print_info "Stopping services..."
    systemctl stop "$SERVICE_NAME" >/dev/null 2>&1 || true
    systemctl disable "$SERVICE_NAME" >/dev/null 2>&1 || true
    rm -f "/etc/systemd/system/${SERVICE_NAME}.service" >/dev/null 2>&1 || true
    systemctl daemon-reload >/dev/null 2>&1 || true

    print_info "Removing files..."
    rm -rf "$INSTALL_DIR"

    print_success "Uninstallation Complete."
  else
    print_info "Cancelled."
  fi
  wait_enter
}

# --- Main Menu Loop ---
while true; do
  print_title
  echo -e " ${GREEN}1)${RESET} 🚀 Install / Re-Install Bot (GitHub)"
  echo -e " ${GREEN}2)${RESET} 🔄 Update Bot (Keep Config) (GitHub)"
  echo -e " ${GREEN}3)${RESET} ♻️  Restart Service"
  echo -e " ${GREEN}4)${RESET} 📜 View Live Logs"
  echo -e " ${GREEN}5)${RESET} ⚙️  Change Config (Token/Port)"
  echo -e " ${GREEN}6)${RESET} 🗑️  Uninstall"
  echo -e " ${GREEN}7)${RESET} 🛠  Fix Database / Dependencies"
  echo -e " ${GREEN}8)${RESET} 🧨 Reset Database (Drop & Recreate)"
  echo -e " ${RED}9) ❌ Exit${RESET}"
  echo ""
  read -r -p " Select Option [1-9]: " OPTION
  case "$OPTION" in
    1) install_process false ;;
    2) install_process true  ;;
    3) full_restart ;;
    4) view_logs ;;
    5) manual_config_menu ;;
    6) uninstall_bot ;;
    7) fix_db_and_dependencies ;;
    8) reset_postgres_database ;;
    9) clear; exit 0 ;;
    *) echo "Invalid Option" ;;
  esac
done
