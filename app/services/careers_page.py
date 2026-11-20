"""
Optional informational note: does the sender's own website describe careers or recruitment?

Off unless CAREERS_PAGE_LOOKUPS=1. It can only ever add a sentence; it never changes the status
or the score, because anyone can publish a convincing careers page on a domain they control, so
a page proves nothing about who sent an offer. Absence is never reported (a missing page says
nothing either). Safety: https only, the hostname must already have passed domain validation,
every resolved address must be public, redirects are not followed, the body is size-capped, and
nothing from the page is stored or shown beyond the fixed sentence.
"""
import ipaddress
import logging
import os
import socket
import ssl
import urllib.request
from typing import Optional

from app.services.env_config import float_env

logger = logging.getLogger(__name__)

PATHS = ("/careers", "/careers/", "/jobs", "/join-us")
MAX_BYTES = 64 * 1024
TIMEOUT_SECONDS = 3.0
KEYWORDS = ("careers", "open positions", "job openings", "internship", "apply now")


def is_enabled() -> bool:
    return os.getenv("CAREERS_PAGE_LOOKUPS") == "1"


def _all_public(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        return False
    addrs = {i[4][0] for i in infos}
    return bool(addrs) and all(ipaddress.ip_address(a).is_global for a in addrs)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # refuse every redirect
        return None


def _open(url: str) -> Optional[bytes]:
    """Body of a 200 response (size-capped) or None. Separate function so tests can replace it."""
    opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    req = urllib.request.Request(url, headers={"User-Agent": "offer-verification-shield (informational check)"})
    timeout = float_env("CAREERS_PAGE_TIMEOUT", TIMEOUT_SECONDS, 0.5, 10.0)
    with opener.open(req, timeout=timeout) as response:  # noqa: S310 (https only, public hosts only)
        return response.read(MAX_BYTES) if response.status == 200 else None


def careers_page_found(domain: str) -> bool:
    """True only if a careers-like page on `domain` answered 200 and reads like one. Fails closed to False."""
    if not is_enabled() or not domain or not _all_public(domain):
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
