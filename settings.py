import os
import json
import logging

# ==============================================================================
# Paths
# ==============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Kept for compatibility with older backup/restore UX (pg_dump output name)
DB_NAME = os.getenv("SONAR_DB_DUMP_NAME", "sonar_ultra_pro.db")

CONFIG_FILE = os.getenv("SONAR_CONFIG_FILE", "sonar_config.json")
KEY_FILE = os.getenv("SONAR_KEY_FILE", "secret.key")
AGENT_FILE_PATH = os.path.join(BASE_DIR, "monitor_agent.py")

# ==============================================================================
# Load JSON config (sonar_config.json)
# ==============================================================================

def _load_json_config(path: str) -> dict:
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f) or {}
    except Exception:
        pass
    return {}

_JSON = _load_json_config(CONFIG_FILE)

# ==============================================================================
# Database (PostgreSQL only)
# ==============================================================================
# Defaults (can be overridden via .env or sonar_config.json)
DB_CONFIG = {
    "dbname": os.getenv("SONAR_DB_NAME", str(_JSON.get("db_name", "sonar_ultra_pro"))),
    "user": os.getenv("SONAR_DB_USER", str(_JSON.get("db_user", "sonar_user"))),
    "password": os.getenv("SONAR_DB_PASSWORD", str(_JSON.get("db_password", "SonarPassword2025"))),
    "host": os.getenv("SONAR_DB_HOST", str(_JSON.get("db_host", "localhost"))),
    "port": os.getenv("SONAR_DB_PORT", str(_JSON.get("db_port", "5432"))),
}

# ==============================================================================
# Admin & Agent port
# ==============================================================================
SUPER_ADMIN_ID = int(os.getenv("SONAR_ADMIN_ID", _JSON.get("admin_id", 0) or 0))
AGENT_PORT = int(os.getenv("SONAR_AGENT_PORT", _JSON.get("agent_port", 8080) or 8080))

# ==============================================================================
# Subscription plans
# ==============================================================================
SUBSCRIPTION_PLANS = {
    "bronze": {
        "name": "برنزی 🥉",
        "limit": 5,
        "days": 30,
        "price": 100000,
        "desc": "مناسب برای استفاده شخصی",
    },
    "silver": {
        "name": "نقره‌ای 🥈",
        "limit": 10,
        "days": 30,
        "price": 180000,
        "desc": "مناسب برای تیم‌های کوچک",
    },
    "gold": {
        "name": "طلایی 🥇",
        "limit": 15,
        "days": 30,
        "price": 240000,
        "desc": "حرفه‌ای و بدون محدودیت",
    },
}

# ==============================================================================
# Payment info default
# ==============================================================================
PAYMENT_INFO = {
    "card": {"number": "6037-9979-0000-0000", "name": "نام صاحب حساب"},
    "tron": {"address": "TRC20_WALLET_ADDRESS_HERE", "network": "TRC20"},
}

# ==============================================================================
# Monitoring config
# ==============================================================================
DEFAULT_INTERVAL = 120
DOWN_RETRY_LIMIT = 3

# ==============================================================================
# WebSocket stability settings (client pool)
# ==============================================================================
WS_POOL_MAX_PER_KEY = int(os.getenv("SONAR_WS_POOL_MAX", _JSON.get("ws_pool_max", 5) or 5))
WS_OPEN_TIMEOUT = float(os.getenv("SONAR_WS_OPEN_TIMEOUT", _JSON.get("ws_open_timeout", 6) or 6))
WS_CLOSE_TIMEOUT = float(os.getenv("SONAR_WS_CLOSE_TIMEOUT", _JSON.get("ws_close_timeout", 6) or 6))
WS_PING_INTERVAL = float(os.getenv("SONAR_WS_PING_INTERVAL", _JSON.get("ws_ping_interval", 20) or 20))
WS_PING_TIMEOUT = float(os.getenv("SONAR_WS_PING_TIMEOUT", _JSON.get("ws_ping_timeout", 20) or 20))
WS_ACQUIRE_TIMEOUT = float(os.getenv("SONAR_WS_ACQUIRE_TIMEOUT", _JSON.get("ws_acquire_timeout", 30) or 30))

# If agent outputs large payloads, max_size=None is safest.
WS_MAX_MESSAGE_SIZE = None

# Professional reconnect policy (exponential backoff + jitter)
WS_CONNECT_RETRIES = int(os.getenv("SONAR_WS_CONNECT_RETRIES", _JSON.get("ws_connect_retries", 6) or 6))
WS_BACKOFF_BASE = float(os.getenv("SONAR_WS_BACKOFF_BASE", _JSON.get("ws_backoff_base", 0.35) or 0.35))
WS_BACKOFF_FACTOR = float(os.getenv("SONAR_WS_BACKOFF_FACTOR", _JSON.get("ws_backoff_factor", 1.8) or 1.8))
WS_BACKOFF_CAP = float(os.getenv("SONAR_WS_BACKOFF_CAP", _JSON.get("ws_backoff_cap", 10.0) or 10.0))
WS_BACKOFF_JITTER = float(os.getenv("SONAR_WS_BACKOFF_JITTER", _JSON.get("ws_backoff_jitter", 0.25) or 0.25))

# ==============================================================================
# SSH stability settings (fallback)
# ==============================================================================
SSH_CONNECT_TIMEOUT = float(os.getenv("SONAR_SSH_CONNECT_TIMEOUT", _JSON.get("ssh_connect_timeout", 10) or 10))
SSH_BANNER_TIMEOUT = float(os.getenv("SONAR_SSH_BANNER_TIMEOUT", _JSON.get("ssh_banner_timeout", 10) or 10))
SSH_AUTH_TIMEOUT = float(os.getenv("SONAR_SSH_AUTH_TIMEOUT", _JSON.get("ssh_auth_timeout", 15) or 15))
SSH_KEEPALIVE_INTERVAL = int(os.getenv("SONAR_SSH_KEEPALIVE_INTERVAL", _JSON.get("ssh_keepalive_interval", 20) or 20))
SSH_RETRIES = int(os.getenv("SONAR_SSH_RETRIES", _JSON.get("ssh_retries", 1) or 1))
SSH_BACKOFF_BASE = float(os.getenv("SONAR_SSH_BACKOFF_BASE", _JSON.get("ssh_backoff_base", 0.35) or 0.35))
SSH_BACKOFF_FACTOR = float(os.getenv("SONAR_SSH_BACKOFF_FACTOR", _JSON.get("ssh_backoff_factor", 1.8) or 1.8))
SSH_BACKOFF_CAP = float(os.getenv("SONAR_SSH_BACKOFF_CAP", _JSON.get("ssh_backoff_cap", 6.0) or 6.0))
SSH_BACKOFF_JITTER = float(os.getenv("SONAR_SSH_BACKOFF_JITTER", _JSON.get("ssh_backoff_jitter", 0.25) or 0.25))

# ==============================================================================
# Logging
# ==============================================================================
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
LOG_LEVEL = logging.INFO
