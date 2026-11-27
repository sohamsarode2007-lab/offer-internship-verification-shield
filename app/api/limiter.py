"""
Rate limiting (slowapi), keyed by client IP.

RATE_LIMIT           default "10/minute"
RATE_LIMIT_ENABLED   default "1"; set "0" to disable (tests)

Behind a reverse proxy, request.client.host is the proxy's address: run uvicorn with
--proxy-headers and --forwarded-allow-ips set to the proxy so the real client IP is used.
RATE_LIMIT_STORAGE_URI  optional shared counter store (e.g. "redis://host:6379") so several workers or
                        copies of the server share one limit. Unset: counters live in process memory, so run
                        a single worker (the Docker image does) or each worker keeps its own count.
"""
import os

from slowapi import Limiter
from slowapi.util import get_remote_address


def configured_rate_limit() -> str:
    return os.getenv("RATE_LIMIT", "10/minute")


RATE_LIMIT = configured_rate_limit()

def build_limiter() -> Limiter:
    return Limiter(
        key_func=get_remote_address,
        enabled=os.getenv("RATE_LIMIT_ENABLED", "1") != "0",
        storage_uri=os.getenv("RATE_LIMIT_STORAGE_URI") or "memory://",
    )


limiter = build_limiter()
