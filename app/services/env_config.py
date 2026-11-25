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


def production_problems(env=None) -> list:
    """Settings that must not reach a production deployment. Empty when ENVIRONMENT is not "production"."""
    env = os.environ if env is None else env
    if env.get("ENVIRONMENT", "").strip().lower() != "production":
        return []
    problems = []
    if len(env.get("INDICATOR_PEPPER", "")) < 32:
        problems.append("INDICATOR_PEPPER must be set to a random value of at least 32 characters")
    origins = [o.strip() for o in env.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
    if not origins:
        problems.append("ALLOWED_ORIGINS must list the site's real origin (the localhost defaults are not for production)")
    elif any(("localhost" in o or "127.0.0.1" in o or o == "*") for o in origins):
        problems.append("ALLOWED_ORIGINS must not contain localhost, 127.0.0.1 or *")
    if env.get("DATABASE_URL", "sqlite").startswith("sqlite"):
        problems.append("DATABASE_URL must point at PostgreSQL, not SQLite")
    if env.get("RATE_LIMIT_ENABLED", "1") == "0":
        problems.append("RATE_LIMIT_ENABLED=0 turns rate limiting off")
    if not env.get("FORWARDED_ALLOW_IPS", "").strip():
        problems.append("FORWARDED_ALLOW_IPS must name the proxy in front of the app (or '*' on a host that always "
                        "proxies), otherwise every visitor shares the proxy's address and one rate limit")
    if env.get("DEMO_MODE", "0") not in ("", "0"):
        problems.append("DEMO_MODE must not be set")
    return problems
