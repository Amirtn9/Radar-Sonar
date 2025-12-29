"""Connection configuration (WS + SSH).

Goal
----
Keep Radar Sonar's existing bot UX intact while making connections stable.

This module is intentionally small and dependency-free.

Config sources (priority)
-------------------------
1) Environment variables (recommended via systemd EnvironmentFile)
2) sonar_config.json
3) Defaults inside settings.py
"""

from __future__ import annotations

import random
from dataclasses import dataclass

# We reuse parsed values from settings.py (which already merges env + json).
from settings import (
    WS_POOL_MAX_PER_KEY,
    WS_OPEN_TIMEOUT,
    WS_CLOSE_TIMEOUT,
    WS_PING_INTERVAL,
    WS_PING_TIMEOUT,
    WS_ACQUIRE_TIMEOUT,
    WS_MAX_MESSAGE_SIZE,
    WS_CONNECT_RETRIES,
    WS_BACKOFF_BASE,
    WS_BACKOFF_FACTOR,
    WS_BACKOFF_CAP,
    WS_BACKOFF_JITTER,
    SSH_CONNECT_TIMEOUT,
    SSH_BANNER_TIMEOUT,
    SSH_AUTH_TIMEOUT,
    SSH_KEEPALIVE_INTERVAL,
    SSH_RETRIES,
    SSH_BACKOFF_BASE,
    SSH_BACKOFF_FACTOR,
    SSH_BACKOFF_CAP,
    SSH_BACKOFF_JITTER,
)


@dataclass(frozen=True)
class WSConnConfig:
    max_per_key: int = int(WS_POOL_MAX_PER_KEY)
    open_timeout: float = float(WS_OPEN_TIMEOUT)
    close_timeout: float = float(WS_CLOSE_TIMEOUT)
    ping_interval: float = float(WS_PING_INTERVAL)
    ping_timeout: float = float(WS_PING_TIMEOUT)
    acquire_timeout: float = float(WS_ACQUIRE_TIMEOUT)
    max_size = WS_MAX_MESSAGE_SIZE

    connect_retries: int = int(WS_CONNECT_RETRIES)
    backoff_base: float = float(WS_BACKOFF_BASE)
    backoff_factor: float = float(WS_BACKOFF_FACTOR)
    backoff_cap: float = float(WS_BACKOFF_CAP)
    backoff_jitter: float = float(WS_BACKOFF_JITTER)


@dataclass(frozen=True)
class SSHConnConfig:
    connect_timeout: float = float(SSH_CONNECT_TIMEOUT)
    banner_timeout: float = float(SSH_BANNER_TIMEOUT)
    auth_timeout: float = float(SSH_AUTH_TIMEOUT)
    keepalive_interval: int = int(SSH_KEEPALIVE_INTERVAL)

    retries: int = int(SSH_RETRIES)
    backoff_base: float = float(SSH_BACKOFF_BASE)
    backoff_factor: float = float(SSH_BACKOFF_FACTOR)
    backoff_cap: float = float(SSH_BACKOFF_CAP)
    backoff_jitter: float = float(SSH_BACKOFF_JITTER)


WS_CONF = WSConnConfig()
SSH_CONF = SSHConnConfig()


def compute_backoff_delay(attempt: int, *, base: float, factor: float, cap: float, jitter: float) -> float:
    """Exponential backoff with jitter.

    attempt: 0,1,2,...
    jitter: fraction (0.25 = ±25%)
    """
    try:
        attempt = int(attempt)
        base = float(base)
        factor = float(factor)
        cap = float(cap)
        jitter = float(jitter)
    except Exception:
        return 0.5

    delay = min(cap, base * (factor ** max(0, attempt)))
    if jitter > 0:
        # jitter in range [1-j, 1+j]
        delay *= (1.0 + random.uniform(-jitter, jitter))
    return max(0.0, delay)


def ws_pool_kwargs() -> dict:
    """kwargs to create WebSocketPool."""
    return {
        "max_per_key": WS_CONF.max_per_key,
        "open_timeout": WS_CONF.open_timeout,
        "close_timeout": WS_CONF.close_timeout,
        "ping_interval": WS_CONF.ping_interval,
        "ping_timeout": WS_CONF.ping_timeout,
        "max_size": WS_CONF.max_size,
        "acquire_timeout": WS_CONF.acquire_timeout,
        "connect_retries": WS_CONF.connect_retries,
        "backoff_base": WS_CONF.backoff_base,
        "backoff_factor": WS_CONF.backoff_factor,
        "backoff_cap": WS_CONF.backoff_cap,
        "backoff_jitter": WS_CONF.backoff_jitter,
    }


def ssh_connect_kwargs() -> dict:
    """kwargs for paramiko.SSHClient.connect."""
    return {
        "timeout": SSH_CONF.connect_timeout,
        "banner_timeout": SSH_CONF.banner_timeout,
        "auth_timeout": SSH_CONF.auth_timeout,
    }
