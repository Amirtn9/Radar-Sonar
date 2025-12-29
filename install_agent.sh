#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Radar Sonar 3.2 - Agent Installer (Target Server)
#   - Python venv: /opt/radar-sonar-agent/.venv
#   - systemd service: sonar-agent
#   - Port collision detection + suggestion
#   - Health check: local WS test
#   - RESET option: remove service + venv + files
#
# Usage:
#   sudo bash install_agent.sh
#   sudo bash install_agent.sh reset
# -----------------------------------------------------------------------------

APP_DIR="/opt/radar-sonar-agent"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$APP_DIR/.env"

SERVICE_AGENT="sonar-agent"

log()  { echo -e "[+] $*"; }
warn() { echo -e "[!] $*"; }
err()  { echo -e "[x] $*" >&2; }

die() { err "$*"; exit 1; }

need_root() {
  if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    die "Run as root: sudo bash install_agent.sh"
  fi
}

command_exists() { command -v "$1" >/dev/null 2>&1; }

pick_free_port() {
  local start="${1:-8080}"
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
    ca-certificates curl jq \
    python3 python3-venv python3-pip \
    || true
}

sync_agent_files() {
  log "Sync agent files to $APP_DIR"
  mkdir -p "$APP_DIR"

  # Only what agent needs (keeps footprint small)
  cp -f "$REPO_DIR/monitor_agent.py" "$APP_DIR/monitor_agent.py"
  chmod 755 "$APP_DIR/monitor_agent.py" || true
}

setup_venv() {
  log "Creating/updating venv (.venv)"
  cd "$APP_DIR"
  if [[ ! -d "$APP_DIR/.venv" ]]; then
    python3 -m venv "$APP_DIR/.venv"
  fi

  "$APP_DIR/.venv/bin/python" -m pip install --upgrade pip setuptools wheel
  # Minimal deps for agent server mode
  "$APP_DIR/.venv/bin/python" -m pip install websockets psutil
}

write_env_file() {
  local agent_port="$1"
  local agent_token="$2"

  log "Writing $ENV_FILE"
  cat > "$ENV_FILE" <<EOF
# Radar Sonar Agent env (loaded by systemd)
SONAR_AGENT_PORT=$agent_port
# Optional shared token. If empty, agent accepts any token (backward compatible)
SONAR_AGENT_TOKEN=$agent_token
EOF
  chmod 600 "$ENV_FILE" || true
}

systemd_install() {
  log "Installing systemd unit: $SERVICE_AGENT"

  cat > "/etc/systemd/system/${SERVICE_AGENT}.service" <<EOF
[Unit]
Description=Radar Sonar WebSocket Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${APP_DIR}/.venv/bin/python -u ${APP_DIR}/monitor_agent.py \${SONAR_AGENT_PORT} \${SONAR_AGENT_TOKEN:+--token \${SONAR_AGENT_TOKEN}}
Restart=always
RestartSec=2
StartLimitIntervalSec=0

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable "$SERVICE_AGENT" >/dev/null 2>&1 || true
  systemctl restart "$SERVICE_AGENT" || true
}

health_check_ws() {
  log "Running local WS health check..."

  if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
  fi

  local port="${SONAR_AGENT_PORT:-8080}"
  local tok="${SONAR_AGENT_TOKEN:-}"  # may be empty

  "$APP_DIR/.venv/bin/python" - <<PY
import asyncio, json, os, sys
import websockets

port = int(os.getenv('SONAR_AGENT_PORT', '8080'))
token = os.getenv('SONAR_AGENT_TOKEN', '')

async def main():
    uri = f"ws://127.0.0.1:{port}"
    try:
        async with websockets.connect(uri, open_timeout=5, close_timeout=5, ping_interval=20, ping_timeout=20, max_size=None) as ws:
            await ws.send(token or 'any')
            await ws.send(json.dumps({'action':'get_stats'}))
            msg = await asyncio.wait_for(ws.recv(), timeout=6)
            data = json.loads(msg)
            if isinstance(data, dict) and 'cpu' in data:
                print('WS: OK')
                return
            print('WS: FAIL (unexpected response)', data)
            sys.exit(2)
    except Exception as e:
        print('WS: FAIL', e)
        sys.exit(2)

asyncio.run(main())
PY

  systemctl is-active --quiet "$SERVICE_AGENT" && log "Agent service: active" || warn "Agent service: not active"
}

show_logs_menu() {
  echo
  echo "Which logs?"
  echo " 1) agent"
  echo " 2) exit"
  read -r -p "Select [1-2]: " ch || true

  case "${ch:-}" in
    1) journalctl -u "$SERVICE_AGENT" -n 250 --no-pager ;;
    *) true ;;
  esac
}

reset_all() {
  warn "RESET requested: removing agent service + venv + files"

  systemctl stop "$SERVICE_AGENT" >/dev/null 2>&1 || true
  systemctl disable "$SERVICE_AGENT" >/dev/null 2>&1 || true
  rm -f "/etc/systemd/system/${SERVICE_AGENT}.service" || true
  systemctl daemon-reload || true

  rm -rf "$APP_DIR" || true

  log "RESET done. Now rerun: sudo bash install_agent.sh"
}

main() {
  need_root

  if [[ "${1:-}" == "reset" || "${1:-}" == "--reset" ]]; then
    reset_all
    exit 0
  fi

  apt_install_prereqs
  sync_agent_files
  setup_venv

  local PORT_DEFAULT
  PORT_DEFAULT="$(pick_free_port 8080)"

  if [[ "$PORT_DEFAULT" != "8080" ]]; then
    warn "Port 8080 is busy. Suggested free port: $PORT_DEFAULT"
  fi

  local AGENT_PORT
  read -r -p "Agent port [default ${PORT_DEFAULT}]: " AGENT_PORT || true
  AGENT_PORT="${AGENT_PORT:-$PORT_DEFAULT}"

  # Optional token (empty => backward compatible)
  local AGENT_TOKEN
  read -r -p "Agent token (optional, leave empty to disable auth): " AGENT_TOKEN || true
  AGENT_TOKEN="${AGENT_TOKEN:-}"

  write_env_file "$AGENT_PORT" "$AGENT_TOKEN"
  systemd_install
  health_check_ws

  log "Done. Agent is running as systemd service: ${SERVICE_AGENT}"
  show_logs_menu
}

main "$@"
