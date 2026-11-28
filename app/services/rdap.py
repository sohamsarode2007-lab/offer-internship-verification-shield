"""Domain registration date from RDAP, asked of the registry's own server (RFC 7480-7484, bootstrap RFC 9224).

Only the domain being checked is sent, to the registry that operates its TLD; nothing from the offer text is sent.
Failures of any kind return None and the caller falls back to WHOIS or "age unknown". RDAP_LOOKUPS=0 turns it off.
"""
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from app.services import safe_fetch
from app.services.env_config import float_env

logger = logging.getLogger(__name__)

BOOTSTRAP_HOST = "data.iana.org"
BOOTSTRAP_PATH = "/rdap/dns.json"
BOOTSTRAP_TTL_SECONDS = 24 * 3600
HIT_TTL_SECONDS = 24 * 3600
MISS_TTL_SECONDS = 15 * 60
MAX_CACHED_DOMAINS = 2000
MAX_BODY_BYTES = 256 * 1024
_DOMAIN_RE = re.compile(r"^(?=.{4,253}$)[a-z0-9-]{1,63}(?:\.[a-z0-9-]{1,63})+$")

_lock = threading.Lock()
_bootstrap: Tuple[float, Dict[str, List[str]]] = (0.0, {})
_cache: Dict[str, Tuple[float, Optional[datetime]]] = {}


def enabled() -> bool:
    return os.getenv("RDAP_LOOKUPS", "1").strip() != "0"


def _timeout() -> float:
    return float_env("RDAP_TIMEOUT", 3.0, 0.5, 10.0)


def _get_json(host: str, path: str):
    status, _location, _cert, body = safe_fetch.request("GET", "https", host, path, timeout=_timeout(),
                                                       read_bytes=MAX_BODY_BYTES, user_agent="offer-verification-shield (rdap)")
    if status != 200:
        raise ValueError(f"HTTP {status}")
    return json.loads(body)


def _servers_by_tld() -> Dict[str, List[str]]:
    global _bootstrap
    fetched_at, table = _bootstrap
    if table and time.monotonic() - fetched_at < BOOTSTRAP_TTL_SECONDS:
        return table
    data = _get_json(BOOTSTRAP_HOST, BOOTSTRAP_PATH)
    table = {}
    for tlds, urls in data.get("services", []):
        https_urls = [u for u in urls if isinstance(u, str) and u.startswith("https://")]
        for tld in tlds:
            table[str(tld).lower()] = https_urls
    _bootstrap = (time.monotonic(), table)
    return table


def _registration_date(payload) -> Optional[datetime]:
    for event in payload.get("events", []) if isinstance(payload, dict) else []:
        if event.get("eventAction") == "registration":
            try:
                parsed = datetime.fromisoformat(str(event["eventDate"]).replace("Z", "+00:00"))
            except (KeyError, ValueError):
                return None
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _lookup(domain: str) -> Optional[datetime]:
    urls = _servers_by_tld().get(domain.rsplit(".", 1)[-1], [])
    if not urls:
        return None
    base = urls[0].split("://", 1)[1]
    host, _, base_path = base.partition("/")
    path = "/" + base_path.rstrip("/") + "/domain/" + domain if base_path.strip("/") else "/domain/" + domain
    return _registration_date(_get_json(host, path))


def creation_date(domain: str) -> Optional[datetime]:
    domain = (domain or "").strip().lower().rstrip(".")
    if not enabled() or not _DOMAIN_RE.match(domain):
        return None
    now = time.monotonic()
    with _lock:
        cached = _cache.get(domain)
    if cached and now < cached[0]:
        return cached[1]
    try:
        created = _lookup(domain)
    except Exception as exc:
        logger.warning("[RDAP] lookup unavailable: %s", type(exc).__name__)
        created = None
    with _lock:
        if len(_cache) >= MAX_CACHED_DOMAINS:
            _cache.clear()
        _cache[domain] = (now + (HIT_TTL_SECONDS if created else MISS_TTL_SECONDS), created)
    return created
