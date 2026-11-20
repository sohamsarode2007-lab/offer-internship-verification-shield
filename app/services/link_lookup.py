"""
Opt-in link lookups (informational only: never change the score, never say a link is "safe").

Runs only when BOTH are true: the operator set LINK_LOOKUPS=1, and this request carried the person's consent.
For at most MAX_LINKS links found in the offer it can:

  1. Ask Google Web Risk (Lookup API) whether the address is on Google's threat lists.
     Result is only ever "threat-listed" or "unknown". Not being listed proves nothing.
     Needs WEB_RISK_API_KEY; without a key this step is skipped.
  2. Visit the link from this server to follow its redirects (HEAD, no body read, at most MAX_HOPS hops, public
     addresses only) and read the TLS certificate of the landing site.

Privacy: only a minimised address leaves this server (scheme + host + a short path; never the query, fragment,
login part, or a path that looks like it holds a name, email or number). The person's own IP address is never
involved. Links are never logged or stored, and notes show only the host, never the full link. Visiting a link
tells its owner that some server opened it; that is why this needs consent.
"""
import http.client
import json
import logging
import os
import re
import ssl
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from app.services import careers_page, domain_verification, url_evidence
from app.services.env_config import float_env

logger = logging.getLogger(__name__)

MAX_LINKS = 3
MAX_HOPS = 4
MAX_PATH_CHARS = 60
TIMEOUT_SECONDS = 4.0
WEB_RISK_URL = "https://webrisk.googleapis.com/v1/uris:search"
THREAT_TYPES = ("MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE")
NEW_CERT_DAYS = 14
_URL_RE = url_evidence._URL_RE
_PII_PATH_RE = re.compile(r"@|\d{8,}|%40", re.I)


def is_enabled() -> bool:
    return os.getenv("LINK_LOOKUPS") == "1"


def minimise(raw: str) -> Optional[str]:
    """Address that is safe to send onward, or None (login part, odd scheme, raw IP or no host are dropped)."""
    raw = raw.rstrip(".,;:!?")
    if not raw.lower().startswith("http"):
        raw = "http://" + raw
    try:
        parts = urllib.parse.urlsplit(raw)
        host = (parts.hostname or "").lower()
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not host or "@" in parts.netloc or "." not in host:
        return None
    if re.fullmatch(r"[\d.]+|[0-9a-f:]+", host):
        return None
    path = parts.path or "/"
    if len(path) > MAX_PATH_CHARS or _PII_PATH_RE.search(urllib.parse.unquote(path)):
        path = "/"
    return f"{parts.scheme}://{host}{path}"


def extract_links(text: str) -> List[str]:
    seen: List[str] = []
    for match in _URL_RE.finditer(text or ""):
        link = minimise(match.group(0))
        if link and link not in seen:
            seen.append(link)
        if len(seen) >= MAX_LINKS:
            break
    return seen


def _get_json(url: str) -> Dict[str, Any]:
    """Separate function so tests can replace it. Never log `url`: it carries the API key."""
    timeout = float_env("LINK_LOOKUP_TIMEOUT", TIMEOUT_SECONDS, 0.5, 10.0)
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 (fixed https host)
        return json.loads(response.read(16 * 1024))


def web_risk(link: str) -> Dict[str, Any]:
    key = os.getenv("WEB_RISK_API_KEY", "")
    if not key:
        return {"status": "unknown", "threat_types": []}
    query = urllib.parse.urlencode([("threatTypes", t) for t in THREAT_TYPES] + [("uri", link), ("key", key)])
    try:
        data = _get_json(f"{WEB_RISK_URL}?{query}")
    except Exception as exc:  # network, quota, bad key, odd payload: never fail the analysis
        logger.warning("[LINK_LOOKUP] Web Risk unavailable: %s", type(exc).__name__)
        return {"status": "unknown", "threat_types": []}
    types = (data.get("threat") or {}).get("threatTypes") if isinstance(data, dict) else None
    if types:
        return {"status": "threat-listed", "threat_types": [t for t in types if t in THREAT_TYPES]}
    return {"status": "unknown", "threat_types": []}


def _head(link: str):
    """One HEAD request, no redirect following. Returns (status, location, cert_info or None). Replaceable in tests."""
    parts = urllib.parse.urlsplit(link)
    timeout = float_env("LINK_LOOKUP_TIMEOUT", TIMEOUT_SECONDS, 0.5, 10.0)
    path = (parts.path or "/")
    if parts.scheme == "https":
        conn = http.client.HTTPSConnection(parts.hostname, parts.port or 443, timeout=timeout,
                                           context=ssl.create_default_context())
    else:
        conn = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=timeout)
    try:
        conn.request("HEAD", path, headers={"User-Agent": "offer-verification-shield (link check)"})
        cert = conn.sock.getpeercert() if parts.scheme == "https" else None
        response = conn.getresponse()
        return response.status, response.getheader("Location"), cert
    finally:
        conn.close()


def _cert_age_days(cert: Optional[dict]) -> Optional[int]:
    try:
        return max(0, int((time.time() - ssl.cert_time_to_seconds(cert["notBefore"])) // 86400))
    except Exception:
        return None


def follow(link: str) -> Dict[str, Any]:
    """Follow redirects with limits. Result holds only host-level facts."""
    current, hops, tls, cert_age = link, 0, "unknown", None
    start_host = urllib.parse.urlsplit(link).hostname or ""
    try:
        for _ in range(MAX_HOPS + 1):
            host = urllib.parse.urlsplit(current).hostname or ""
            if not careers_page._all_public(host):
                return {"hops": hops, "landing_host": None, "tls": "unknown", "cert_age_days": None, "stopped": True}
            try:
                status, location, cert = _head(current)
            except ssl.SSLCertVerificationError:
                return {"hops": hops, "landing_host": host, "tls": "invalid", "cert_age_days": None, "stopped": False}
            if current.startswith("https"):
                tls, cert_age = "valid", _cert_age_days(cert)
            if status in (301, 302, 303, 307, 308) and location and hops < MAX_HOPS:
                nxt = minimise(urllib.parse.urljoin(current, location))
                if not nxt:
                    break
                current, hops = nxt, hops + 1
                continue
            break
    except Exception as exc:
        logger.info("[LINK_LOOKUP] visit unavailable: %s", type(exc).__name__)
        return {"hops": hops, "landing_host": None, "tls": "unknown", "cert_age_days": None, "stopped": True}
    landing = urllib.parse.urlsplit(current).hostname
    different = bool(landing) and domain_verification.registrable_domain(landing)[0] != \
        domain_verification.registrable_domain(start_host)[0]
    return {"hops": hops, "landing_host": landing if different else None, "tls": tls,
            "cert_age_days": cert_age, "stopped": False}


def build_link_checks(text: str, consent: bool) -> Dict[str, Any]:
    """{'notes': [...], 'threat_listed': bool}. Empty unless enabled by the operator and consented to."""
    out: Dict[str, Any] = {"notes": [], "threat_listed": False}
    if not (is_enabled() and consent):
        return out
    for link in extract_links(text):
        host = urllib.parse.urlsplit(link).hostname
        risk = web_risk(link)
        if risk["status"] == "threat-listed":
            out["threat_listed"] = True
            kinds = ", ".join(t.replace("_", " ").lower() for t in risk["threat_types"]) or "a threat"
            out["notes"].append(f"Google Web Risk lists '{host}' as dangerous ({kinds}). Do not open it.")
        visit = follow(link)
        if visit["landing_host"]:
            out["notes"].append(f"The link to '{host}' redirects to a different site, '{visit['landing_host']}'.")
        elif visit["hops"] >= 3:
            out["notes"].append(f"The link to '{host}' passes through {visit['hops']} redirects before it lands.")
        if visit["tls"] == "invalid":
            out["notes"].append(f"The site '{visit['landing_host'] or host}' has a security certificate that does not check out.")
        elif visit["cert_age_days"] is not None and visit["cert_age_days"] < NEW_CERT_DAYS:
            out["notes"].append(f"The site '{host}' got its security certificate only {visit['cert_age_days']} days ago "
                                "(weak signal: many genuine sites renew often).")
    if out["notes"]:
        out["notes"].append("Link lookups can only find known problems. A link that is not flagged is not proven safe.")
    return out
