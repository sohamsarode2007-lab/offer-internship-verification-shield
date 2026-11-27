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
import json
import logging
import os
import re
import ssl
import concurrent.futures
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from app.services import domain_verification, request_budget, safe_fetch, url_evidence
from app.services.env_config import float_env

logger = logging.getLogger(__name__)

MAX_LINKS = 3
MAX_HOPS = 4
MAX_PATH_CHARS = 60
TIMEOUT_SECONDS = 4.0
OVERALL_DEADLINE_SECONDS = 8.0      # whole link-check job, all links in parallel
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
    if not key or not request_budget.try_spend("web_risk"):
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


def _head(link: str, timeout: Optional[float] = None):
    """One HEAD request through the pinned-address client (no redirect following). Replaceable in tests.

    Returns (status, Location header, certificate or None).
    """
    parts = urllib.parse.urlsplit(link)
    timeout = timeout or float_env("LINK_LOOKUP_TIMEOUT", TIMEOUT_SECONDS, 0.5, 10.0)
    status, location, cert, _ = safe_fetch.request("HEAD", parts.scheme, parts.hostname, parts.path or "/",
                                                   timeout=timeout)
    return status, location, cert


def _cert_age_days(cert: Optional[dict]) -> Optional[int]:
    try:
        return max(0, int((time.time() - ssl.cert_time_to_seconds(cert["notBefore"])) // 86400))
    except Exception:
        return None


def follow(link: str, deadline: Optional[float] = None) -> Dict[str, Any]:
    """Follow redirects, hop by hop, within a deadline. Result holds only host-level facts."""
    deadline = deadline or time.monotonic() + OVERALL_DEADLINE_SECONDS
    current, hops, tls, cert_age = link, 0, "unknown", None
    start_host = urllib.parse.urlsplit(link).hostname or ""
    stopped = {"hops": hops, "landing_host": None, "tls": "unknown", "cert_age_days": None, "stopped": True}
    try:
        for _ in range(MAX_HOPS + 1):
            tls, cert_age = "unknown", None
            remaining = deadline - time.monotonic()
            if remaining <= 0.2 or not request_budget.try_spend("link_visit"):
                return {**stopped, "hops": hops}
            host = urllib.parse.urlsplit(current).hostname or ""
            try:
                status, location, cert = _head(current, min(remaining, float_env("LINK_LOOKUP_TIMEOUT",
                                                                                 TIMEOUT_SECONDS, 0.5, 10.0)))
            except ssl.SSLCertVerificationError:
                different = bool(host) and domain_verification.registrable_domain(host)[0] != \
                    domain_verification.registrable_domain(start_host)[0]
                return {"hops": hops, "landing_host": host if different else None,
                        "tls": "invalid", "cert_age_days": None, "stopped": False}
            except safe_fetch.UnsafeTarget:
                return {**stopped, "hops": hops}
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
        return {**stopped, "hops": hops}
    landing = urllib.parse.urlsplit(current).hostname
    different = bool(landing) and domain_verification.registrable_domain(landing)[0] != \
        domain_verification.registrable_domain(start_host)[0]
    return {"hops": hops, "landing_host": landing if different else None, "tls": tls,
            "cert_age_days": cert_age, "stopped": False}


def _check_one(link: str, deadline: float) -> Dict[str, Any]:
    return {"link": link, "risk": web_risk(link), "visit": follow(link, deadline)}


def build_link_checks(text: str, consent: bool) -> Dict[str, Any]:
    """{'notes': [...], 'threat_listed': bool}. Empty unless enabled by the operator and consented to.

    All links are checked in parallel under one overall deadline, so one request can never hold a worker for
    more than OVERALL_DEADLINE_SECONDS however many hops or slow servers there are.
    """
    out: Dict[str, Any] = {"notes": [], "threat_listed": False}
    if not (is_enabled() and consent):
        return out
    links = extract_links(text)
    if not links:
        return out
    deadline = time.monotonic() + OVERALL_DEADLINE_SECONDS
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=len(links))
    futures = [pool.submit(_check_one, link, deadline) for link in links]
    results = []
    for link, future in zip(links, futures):
        try:
            results.append(future.result(timeout=max(0.1, deadline - time.monotonic() + 1)))
        except Exception:   # deadline passed or the check failed: report nothing for this link
            results.append({"link": link, "risk": {"status": "unknown", "threat_types": []},
                            "visit": {"hops": 0, "landing_host": None, "tls": "unknown", "cert_age_days": None}})
    pool.shutdown(wait=False, cancel_futures=True)
    for item in results:
        host = urllib.parse.urlsplit(item["link"]).hostname
        risk, visit = item["risk"], item["visit"]
        if risk["status"] == "threat-listed":
            out["threat_listed"] = True
            kinds = ", ".join(t.replace("_", " ").lower() for t in risk["threat_types"]) or "a threat"
            out["notes"].append(f"Google Web Risk lists '{host}' as dangerous ({kinds}). Do not open it.")
        if visit["landing_host"]:
            out["notes"].append(f"The link to '{host}' redirects to a different site, '{visit['landing_host']}'.")
        elif visit["hops"] >= 3:
            out["notes"].append(f"The link to '{host}' passes through {visit['hops']} redirects before it lands.")
        if visit["tls"] == "invalid":
            out["notes"].append(f"The site '{visit['landing_host'] or host}' has a security certificate that does not check out.")
        elif visit["cert_age_days"] is not None and visit["cert_age_days"] < NEW_CERT_DAYS:
            out["notes"].append(f"The site '{visit['landing_host'] or host}' got its security certificate only {visit['cert_age_days']} days ago "
                                "(weak signal: many genuine sites renew often).")
    if out["notes"]:
        out["notes"].append("Link lookups can only find known problems. A link that is not flagged is not proven safe.")
    return out
