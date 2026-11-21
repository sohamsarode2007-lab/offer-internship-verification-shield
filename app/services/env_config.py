"""Small, safe readers for optional tuning variables (never raise, always bounded)."""
import os


def float_env(name: str, default: float, low: float, high: float) -> float:
    """Float from the environment, clamped to [low, high]; the default when unset or not a number."""
    raw = os.getenv(name, "").strip()
    try:
        value = float(raw)
    except ValueError:
        return default
    if value != value:  # NaN
        return default
    return max(low, min(high, value))


def https_url_env(name: str, default: str) -> str:
    """URL from the environment; only https is accepted (anything else falls back to the default)."""
    raw = os.getenv(name, "").strip().rstrip("/")
    return raw if raw.lower().startswith("https://") and len(raw) > len("https://") else default
