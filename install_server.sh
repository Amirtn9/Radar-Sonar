#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Radar Sonar 3.2 - Server Installer
#   - PostgreSQL (project database)
#   - Python venv (/opt/radar-sonar/.venv) and requirements
#   - systemd services:
#       1) sonar-bot  -> /opt/radar-sonar/bot.py  (Telegram bot)
#       2) sonar-api  -> local lightweight HTTP server for health (optional)
#   - Health checks + quick log viewer
#   - RESET option: remove services + venv + drop DB/user, then reinstall
#
# Usage:
#   sudo bash install_server.sh
#   sudo bash install_server.sh reset
# -----------------------------------------------------------------------------

APP_DIR="/opt/radar-sonar"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$APP_DIR/.env"
CONFIG_JSON="$APP_DIR/sonar_config.json"

SERVICE_BOT="sonar-bot"
SERVICE_API="sonar-api"

log() { echo -e "[+] $*"; }
warn() { echo -e "[!] $*"; }
err() { echo -e "[x] $*" >&2; }

die() { err "$*"; exit 1; }

need_root() {
  if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    die "Run as root: sudo bash install_server.sh"
  fi
}

command_exists() { command -v "$1" >/dev/null 2>&1; }

pick_free_port() {
  local start="${1:-8010}"
  local p="$start"
  while ss -lnt 2>/dev/null | awk '{print $4}' | grep -qE ":${p}$"; do
    p=$((p+1))
  done
  echo "$p"
}

apt_install_prereqs() {
  log "Installing apt prerequisites..."
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y --no-install-recommends \
    ca-certificates curl git jq \
    python3 python3-venv python3-pip \
    build-essential \
    postgresql postgresql-contrib \
    || true
}

sync_project_files() {
  log "Sync project files to $APP_DIR"
  mkdir -p "$APP_DIR"

  if command_exists rsync; then
    rsync -a --delete \
      --exclude ".venv" \
      --exclude "__pycache__" \
      --exclude "*.pyc" \
      "$REPO_DIR/" "$APP_DIR/"
  else
    warn "rsync not found, using cp -r (may leave old files)."
    cp -r "$REPO_DIR/"* "$APP_DIR/" || true
  fi
}

setup_venv() {
  log "Creating/updating venv (.venv)"
  cd "$APP_DIR"
  if [[ ! -d "$APP_DIR/.venv" ]]; then
    python3 -m venv "$APP_DIR/.venv"
  fi

  "$APP_DIR/.venv/bin/python" -m pip install --upgrade pip setuptools wheel
  "$APP_DIR/.venv/bin/python" -m pip install -r "$APP_DIR/requirements.txt"
}

write_env_file() {
  local db_name="$1"
  local db_user="$2"
  local db_pass="$3"
  local db_host="$4"
  local db_port="$5"
  local admin_id="$6"
  local agent_port="$7"
  local api_port="$8"

  log "Writing $ENV_FILE"
  cat > "$ENV_FILE" <<EOF
# Radar Sonar env (loaded by systemd)
SONAR_DB_NAME=$db_name
SONAR_DB_USER=$db_user
SONAR_DB_PASSWORD=$db_pass
SONAR_DB_HOST=$db_host
SONAR_DB_PORT=$db_port

SONAR_ADMIN_ID=$admin_id
SONAR_AGENT_PORT=$agent_port

# Optional: local health server port (sonar-api)
SONAR_LOCAL_API_PORT=$api_port

# WS stability knobs (optional overrides)
# SONAR_WS_CONNECT_RETRIES=6
# SONAR_WS_BACKOFF_BASE=0.35
# SONAR_WS_BACKOFF_CAP=10

# SSH stability knobs (optional overrides)
# SONAR_SSH_CONNECT_TIMEOUT=10
# SONAR_SSH_RETRIES=1
EOF
  chmod 600 "$ENV_FILE" || true
}

postgres_setup() {
  local db_name="$1"
  local db_user="$2"
  local db_pass="$3"

  log "Configuring PostgreSQL (db=$db_name user=$db_user)"
  systemctl enable --now postgresql >/dev/null 2>&1 || true

  # Create user if not exists
  sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${db_user}'" | grep -q 1 \
    || sudo -u postgres psql -c "CREATE USER \"${db_user}\" WITH PASSWORD '${db_pass}';"

  # Create DB if not exists
  sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${db_name}'" | grep -q 1 \
    || sudo -u postgres psql -c "CREATE DATABASE \"${db_name}\" OWNER \"${db_user}\";"

  # Ensure privileges
  sudo -u postgres psql -c "ALTER DATABASE \"${db_name}\" OWNER TO \"${db_user}\";" >/dev/null 2>&1 || true
}

update_config_json() {
  local bot_token="$1"
  local admin_id="$2"
  local agent_port="$3"
  local db_name="$4"
  local db_user="$5"
  local db_pass="$6"
  local db_host="$7"
  local db_port="$8"

  log "Updating $CONFIG_JSON"
  python3 - <<PY
import json, os
p = "${CONFIG_JSON}"
try:
    data = json.load(open(p, 'r', encoding='utf-8')) if os.path.exists(p) else {}
except Exception:
    data = {}

data['bot_token'] = "${bot_token}" or data.get('bot_token')
data['admin_id'] = int("${admin_id}" or 0)
data['agent_port'] = int("${agent_port}" or 8080)

data['db_name'] = "${db_name}"
data['db_user'] = "${db_user}"
data['db_password'] = "${db_pass}"
data['db_host'] = "${db_host}"
data['db_port'] = "${db_port}"

with open(p, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print('ok')
PY
}

systemd_install() {
  local api_port="$1"

  log "Installing systemd units"

  cat > "/etc/systemd/system/${SERVICE_BOT}.service" <<EOF
[Unit]
Description=Radar Sonar Telegram Bot
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${APP_DIR}/.venv/bin/python -u ${APP_DIR}/bot.py
Restart=always
RestartSec=3
# Avoid telegram polling conflicts by keeping a single instance
StartLimitIntervalSec=0

[Install]
WantedBy=multi-user.target
EOF

  # Minimal local health server (does NOT change bot UX)
  cat > "/etc/systemd/system/${SERVICE_API}.service" <<EOF
[Unit]
Description=Radar Sonar Local Health HTTP (optional)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${APP_DIR}/.venv/bin/python -u -m http.server ${api_port} --bind 127.0.0.1
Restart=always
RestartSec=3
StartLimitIntervalSec=0

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable "${SERVICE_BOT}" "${SERVICE_API}" >/dev/null 2>&1 || true
  systemctl restart "${SERVICE_BOT}" "${SERVICE_API}" || true
}

health_checks() {
  log "Running health checks..."

  # DB check
  if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
  fi

  "${APP_DIR}/.venv/bin/python" - <<'PY'
import os, sys
import psycopg2

cfg = dict(
    dbname=os.getenv('SONAR_DB_NAME'),
    user=os.getenv('SONAR_DB_USER'),
    password=os.getenv('SONAR_DB_PASSWORD'),
    host=os.getenv('SONAR_DB_HOST', 'localhost'),
    port=os.getenv('SONAR_DB_PORT', '5432'),
)

try:
    conn = psycopg2.connect(**cfg)
    cur = conn.cursor()
    cur.execute('SELECT 1')
    cur.fetchone()
    cur.close()
    conn.close()
    print('DB: OK')
except Exception as e:
    print('DB: FAIL', e)
    sys.exit(2)
PY

  systemctl is-active --quiet "${SERVICE_BOT}" && log "Bot service: active" || warn "Bot service: not active"
  systemctl is-active --quiet "${SERVICE_API}" && log "API service: active" || warn "API service: not active"
}

show_logs_menu() {
  echo
  echo "Which logs?"
  echo " 1) bot"
  echo " 2) api"
  echo " 3) postgres"
  echo " 4) exit"
  read -r -p "Select [1-4]: " ch || true

  case "${ch:-}" in
    1) journalctl -u "${SERVICE_BOT}" -n 200 --no-pager ;;
    2) journalctl -u "${SERVICE_API}" -n 200 --no-pager ;;
    3) journalctl -u postgresql -n 200 --no-pager ;;
    *) true ;;
  esac
}

reset_all() {
  warn "RESET requested: removing services + venv + dropping project DB/user"

  # Load env if available to know db/user
  if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
  fi

  systemctl stop "${SERVICE_BOT}" "${SERVICE_API}" >/dev/null 2>&1 || true
  systemctl disable "${SERVICE_BOT}" "${SERVICE_API}" >/dev/null 2>&1 || true
  rm -f "/etc/systemd/system/${SERVICE_BOT}.service" "/etc/systemd/system/${SERVICE_API}.service" || true
  systemctl daemon-reload || true

  rm -rf "$APP_DIR/.venv" || true

  # Drop DB (best-effort)
  if command_exists psql; then
    local db_name="${SONAR_DB_NAME:-sonar_ultra_pro}"
    local db_user="${SONAR_DB_USER:-sonar_user}"
    sudo -u postgres psql -c "REVOKE CONNECT ON DATABASE \"${db_name}\" FROM PUBLIC;" >/dev/null 2>&1 || true
    sudo -u postgres psql -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${db_name}';" >/dev/null 2>&1 || true
    sudo -u postgres psql -c "DROP DATABASE IF EXISTS \"${db_name}\";" >/dev/null 2>&1 || true
    sudo -u postgres psql -c "DROP USER IF EXISTS \"${db_user}\";" >/dev/null 2>&1 || true
  fi

  rm -f "$ENV_FILE" || true

  log "RESET done. Now rerun: sudo bash install_server.sh"
}

main() {
  need_root

  if [[ "${1:-}" == "reset" || "${1:-}" == "--reset" ]]; then
    reset_all
    exit 0
  fi

  apt_install_prereqs
  sync_project_files
  setup_venv

  # Gather minimal inputs
  local BOT_TOKEN=""
  if [[ -f "$CONFIG_JSON" ]]; then
    BOT_TOKEN="$(python3 -c 'import json; import os; p="'"$CONFIG_JSON"'";\
try:\
 d=json.load(open(p));\
 print(d.get("bot_token",""));\
except Exception:\
 print("")' 2>/dev/null || true)"
  fi
  read -r -p "Bot token (leave empty to keep current): " in_tok || true
  if [[ -n "${in_tok:-}" ]]; then BOT_TOKEN="$in_tok"; fi

  local ADMIN_ID="0"
  read -r -p "Super admin Telegram user_id (number): " ADMIN_ID || true
  ADMIN_ID="${ADMIN_ID:-0}"

  local AGENT_PORT
  read -r -p "Agent port used on target servers [default 8080]: " AGENT_PORT || true
  AGENT_PORT="${AGENT_PORT:-8080}"

  local API_PORT
  API_PORT="$(pick_free_port 8010)"
  read -r -p "Local API (health) port [default ${API_PORT}]: " in_api || true
  if [[ -n "${in_api:-}" ]]; then API_PORT="$in_api"; fi

  local DB_NAME="sonar_ultra_pro"
  local DB_USER="sonar_user"
  local DB_PASS
  DB_PASS="$(openssl rand -hex 12 2>/dev/null || date +%s%N | sha256sum | head -c 24)"

  read -r -p "Postgres db name [default ${DB_NAME}]: " in_db || true
  if [[ -n "${in_db:-}" ]]; then DB_NAME="$in_db"; fi
  read -r -p "Postgres user [default ${DB_USER}]: " in_user || true
  if [[ -n "${in_user:-}" ]]; then DB_USER="$in_user"; fi
  read -r -p "Postgres password (empty = auto-generate): " in_pass || true
  if [[ -n "${in_pass:-}" ]]; then DB_PASS="$in_pass"; fi

  postgres_setup "$DB_NAME" "$DB_USER" "$DB_PASS"
  write_env_file "$DB_NAME" "$DB_USER" "$DB_PASS" "localhost" "5432" "$ADMIN_ID" "$AGENT_PORT" "$API_PORT"
  update_config_json "$BOT_TOKEN" "$ADMIN_ID" "$AGENT_PORT" "$DB_NAME" "$DB_USER" "$DB_PASS" "localhost" "5432"

  systemd_install "$API_PORT"
  health_checks

  log "Done. Bot is running as systemd service: ${SERVICE_BOT}"
  show_logs_menu
}

main "$@"
