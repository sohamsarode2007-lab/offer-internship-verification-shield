"""
Daily budget for outbound lookups that count against a free quota (in memory, per process, resets each UTC day).

It protects the free tier and the operator's bill, not the person: when a budget is spent the lookup is simply
skipped and the check reports nothing extra. Counts are numbers only; nothing about a request is kept.
A multi-worker deployment gets one budget per worker (so the effective limit is workers x budget).
"""
import threading
from datetime import datetime, timezone
from typing import Dict

from app.services.env_config import float_env

DEFAULTS = {"web_risk": 3000.0}  # ~90,000 a month, under Web Risk's 100,000 free lookups
_lock = threading.Lock()
_state: Dict[str, Dict] = {}


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def limit(name: str) -> int:
    return int(float_env(f"{name.upper()}_DAILY_BUDGET", DEFAULTS[name], 0, 10_000_000))


def used(name: str) -> int:
    with _lock:
        entry = _state.get(name)
        return entry["count"] if entry and entry["day"] == _today() else 0


def try_spend(name: str, amount: int = 1) -> bool:
    """True and counted if the day's budget allows `amount` more calls; otherwise False and nothing counted."""
    with _lock:
        entry = _state.get(name)
        if not entry or entry["day"] != _today():
            entry = _state[name] = {"day": _today(), "count": 0}
        if entry["count"] + amount > limit(name):
            return False
        entry["count"] += amount
        return True


def reset() -> None:
    with _lock:
        _state.clear()
