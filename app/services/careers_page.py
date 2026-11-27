"""
Optional informational note: does the sender's own website describe careers or recruitment?

Off unless CAREERS_PAGE_LOOKUPS=1. It can only ever add a sentence; it never changes the status
or the score, because anyone can publish a convincing careers page on a domain they control, so
a page proves nothing about who sent an offer. Absence is never reported (a missing page says
nothing either). Safety: https only, the hostname must already have passed domain validation,
the name is resolved once, every address must be public and the connection goes to that exact address (no DNS
rebinding), redirects are not followed, the body is size-capped, and
nothing from the page is stored or shown beyond the fixed sentence.
"""
import logging
import os
import urllib.parse
from typing import Optional

from app.services import safe_fetch
from app.services.env_config import float_env

logger = logging.getLogger(__name__)

PATHS = ("/careers", "/careers/", "/jobs", "/join-us")
MAX_BYTES = 64 * 1024
TIMEOUT_SECONDS = 3.0
KEYWORDS = ("careers", "open positions", "job openings", "internship", "apply now")


def is_enabled() -> bool:
    return os.getenv("CAREERS_PAGE_LOOKUPS") == "1"


def _open(url: str) -> Optional[bytes]:
    """Body of a 200 response (size-capped) or None, through the pinned-address client (no redirects).

    Separate function so tests can replace it. Raises safe_fetch.UnsafeTarget for non-public hosts.
    """
    parts = urllib.parse.urlsplit(url)
    timeout = float_env("CAREERS_PAGE_TIMEOUT", TIMEOUT_SECONDS, 0.5, 10.0)
    status, _location, _cert, body = safe_fetch.request("GET", "https", parts.hostname or "", parts.path or "/",
                                                        timeout=timeout, read_bytes=MAX_BYTES,
                                                        user_agent="offer-verification-shield (informational check)")
    return body if status == 200 else None


def careers_page_found(domain: str) -> bool:
    """True only if a careers-like page on `domain` answered 200 and reads like one. Fails closed to False."""
    if not is_enabled() or not domain:
        return False
    for path in PATHS:
        try:
            body = _open(f"https://{domain}{path}")
        except Exception as exc:
            logger.info("[CAREERS_PAGE] lookup unavailable: %s", type(exc).__name__)
            continue
        if body and any(k in body.decode("utf-8", errors="ignore").lower() for k in KEYWORDS):
            return True
    return False
