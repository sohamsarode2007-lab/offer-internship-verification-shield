"""
Optional "first seen" evidence from the Internet Archive's public CDX index.

Off unless INFRA_AGE_LOOKUPS=1. It is used only when WHOIS/RDAP could not give a domain age, and
only adds an informational sentence: a site that was archived years ago is not a new throwaway
domain, but an archived copy proves nothing about who sends this offer, so it never changes the
status or adds or removes risk points. Any error, timeout or odd payload returns None (fail
closed: no sentence at all). The request is made only for a hostname that already passed the
domain check's format validation.
"""
import json
import logging
import os
import re
import urllib.parse
import urllib.request
from typing import Optional

from app.services.env_config import float_env

logger = logging.getLogger(__name__)

CDX_URL = "https://web.archive.org/cdx/search/cdx"
TIMEOUT_SECONDS = 3.0
MAX_RESPONSE_BYTES = 16 * 1024
_TIMESTAMP_RE = re.compile(r"^(\d{4})(\d{2})\d{8}$")


def is_enabled() -> bool:
    return os.getenv("INFRA_AGE_LOOKUPS") == "1"


def _open(url: str) -> bytes:
    """Fetch the URL body (size-capped). Separate function so tests can replace it."""
    with urllib.request.urlopen(url, timeout=float_env("INFRA_AGE_TIMEOUT", TIMEOUT_SECONDS, 0.5, 10.0)) as response:  # noqa: S310 (fixed https host)
        return response.read(MAX_RESPONSE_BYTES)


def first_capture_month(domain: str) -> Optional[str]:
    """Year-month ('2019-03') of the earliest archived successful capture, or None."""
    if not is_enabled() or not domain:
        return None
    query = urllib.parse.urlencode({"url": domain, "limit": "1", "output": "json",
                                    "fl": "timestamp", "filter": "statuscode:200"})
    try:
        rows = json.loads(_open(f"{CDX_URL}?{query}"))
        stamp = rows[1][0]  # row 0 is the header ["timestamp"]
        match = _TIMESTAMP_RE.match(stamp)
        return f"{match.group(1)}-{match.group(2)}" if match else None
    except Exception as exc:  # network, timeout, JSON or shape problem
        logger.warning("[WEB_ARCHIVE] first-capture lookup unavailable: %s", type(exc).__name__)
        return None
