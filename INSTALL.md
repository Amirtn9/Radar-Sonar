# Radar Sonar 3.2 (based on Radar Sonar 2.8)

Goal: keep the existing Telegram bot UX unchanged, while making **install + connections** stable.

## 1) Server Install (Bot + PostgreSQL + systemd)

Run on your main server (Central/Bot):

```bash
sudo bash install_server.sh
```

What it does:
- Installs OS prerequisites (python3, venv, postgresql)
- Syncs project to `/opt/radar-sonar`
- Creates venv at `/opt/radar-sonar/.venv` and installs `requirements.txt`
- Creates PostgreSQL user + database (project DB)
- Writes `/opt/radar-sonar/.env` (used by systemd)
- Creates systemd services:
  - `sonar-bot` (Telegram bot)
  - `sonar-api` (optional local health http on 127.0.0.1)
- Runs a DB health check and shows an interactive log menu

Reset (full wipe and reinstall):

```bash
sudo bash install_server.sh reset
sudo bash install_server.sh
```

Logs:

```bash
journalctl -u sonar-bot -n 200 --no-pager
journalctl -u sonar-api -n 200 --no-pager
journalctl -u postgresql -n 200 --no-pager
```

---

## 2) Agent Install (Target Server)

Run on each monitored server:

```bash
sudo bash install_agent.sh
```

What it does:
- Installs OS prerequisites (python3, venv)
- Copies `monitor_agent.py` to `/opt/radar-sonar-agent`
- Creates venv at `/opt/radar-sonar-agent/.venv`
- Installs minimal deps: `websockets` + `psutil`
- Creates systemd service:
  - `sonar-agent`
- Runs a local WebSocket health test (connects to 127.0.0.1:PORT)

Optional token:
- You can set a token during install.
- If empty, agent accepts any token (backward compatible with old behavior).

Reset:

```bash
sudo bash install_agent.sh reset
sudo bash install_agent.sh
```

Logs:

```bash
journalctl -u sonar-agent -n 250 --no-pager
```

---

## Notes

- PostgreSQL only (no sqlite).
- systemd ExecStart always uses the venv python:
  - Server: `/opt/radar-sonar/.venv/bin/python`
  - Agent: `/opt/radar-sonar-agent/.venv/bin/python`
- Connection tuning is centralized via `connections_config.py` (WS + SSH knobs).
