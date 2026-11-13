"""
Rate limiting (slowapi), keyed by client IP.

RATE_LIMIT           default "10/minute" (DEMO_MODE defaults to "100/minute")
RATE_LIMIT_ENABLED   default "1"; set "0" to disable (tests)

Behind a reverse proxy, request.client.host is the proxy's address: run uvicorn with
--proxy-headers and --forwarded-allow-ips set to the proxy so the real client IP is used.
Limits are kept in process memory: with several workers each keeps its own counter.
"""
import os

from slowapi import Limiter
from slowapi.util import get_remote_address

def configured_rate_limit() -> str:
    """Resolve the request limit, with a more generous opt-in demo default."""
    configured = os.getenv("RATE_LIMIT")
    if configured is not None:
        return configured
    return "100/minute" if os.getenv("DEMO_MODE") == "1" else "10/minute"


RATE_LIMIT = configured_rate_limit()

limiter = Limiter(
    key_func=get_remote_address,
    enabled=os.getenv("RATE_LIMIT_ENABLED", "1") != "0",
)
