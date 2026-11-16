"""
Domain Verification Service

IMPORTANT SCOPE: this checks the domain supplied to it. For pasted text and
document uploads that is the domain CLAIMED in the offer. The /analyze route
uses the parsed From domain for original .eml uploads and reports the body-claimed
domain separately. This module itself does not authenticate message headers.

Checks (in order):
  1. Hostname syntax (regex) - invalid -> insufficient_information, no lookups.
  2. Free mailbox (gmail.com, ...)          -> HARD FAIL
  3. Brand lookalike (tcs-careers.in, ...)  -> HARD FAIL
     (exact brand on a non-official domain; brand as a hyphenated token; edit
     distance 1 for 5-7 char brands, 1-2 for 8+ char brands)
  4. DEMO_MODE fixture (see below)          -> pass, clearly labelled
  5. MX record: NXDOMAIN / no MX            -> HARD FAIL
  6. SPF and DMARC TXT records              -> warning only if missing
  7. WHOIS creation date < 30 days          -> HARD FAIL; lookup failure = "age unknown"
     (not counted as a pass).

Overall: any hard fail -> 'fail'; DNS unavailable -> 'insufficient_information';
otherwise 'pass' (warnings listed in details).

Demo mode: if env DEMO_MODE=1 and the domain is listed in env DEMO_FIXTURE_DOMAINS
(comma separated), the result is 'pass' with details starting
"[DEMO FIXTURE — not a live DNS result]". It is never applied silently.
"""
import os
import re
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Union, Optional, List, Tuple

import dns.exception
import dns.resolver
from rapidfuzz.distance import Levenshtein

from app.utils.field_utils import get_field_value
from app.services import brand_advisories, web_archive
from app.utils.email_domains import is_disposable_mailbox, is_free_mailbox

logger = logging.getLogger(__name__)

DNS_TIMEOUT_SECONDS = 3.0
MIN_DOMAIN_AGE_DAYS = 30
DEMO_PREFIX = "[DEMO FIXTURE — not a live DNS result]"


def _make_resolver() -> dns.resolver.Resolver:
    try:
        r = dns.resolver.Resolver()
    except Exception:  # no system resolver configuration (e.g. minimal containers)
        r = dns.resolver.Resolver(configure=False)
        r.nameservers = ["1.1.1.1", "8.8.8.8"]
    r.timeout = DNS_TIMEOUT_SECONDS
    r.lifetime = DNS_TIMEOUT_SECONDS
    return r


# Module-level so tests can patch `_resolver.resolve`.
_resolver = _make_resolver()

HOSTNAME_RE = re.compile(r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")

# Second-level suffixes under which the registrable domain has three labels.
MULTI_LABEL_SUFFIXES = {
    "co.in", "ac.in", "gov.in", "net.in", "org.in", "edu.in", "res.in", "nic.in",
    "firm.in", "gen.in", "ind.in", "mil.in",
    "co.uk", "ac.uk", "org.uk", "gov.uk", "com.au", "net.au", "org.au", "co.jp", "com.sg",
}

# Brand -> official registrable domains. Only widely known corporate domains.
BRAND_OFFICIAL_DOMAINS = {
    "tcs": {"tcs.com", "tcsion.com"},
    "infosys": {"infosys.com"},
    "wipro": {"wipro.com"},
    "hcl": {"hcl.com", "hcltech.com"},
    "hcltech": {"hcltech.com", "hcl.com"},
    "accenture": {"accenture.com"},
    "cognizant": {"cognizant.com"},
    "techmahindra": {"techmahindra.com"},
    "capgemini": {"capgemini.com"},
    "deloitte": {"deloitte.com"},
    "amazon": {"amazon.com", "amazon.in", "amazon.jobs"},
    "google": {"google.com", "google.co.in"},
    "microsoft": {"microsoft.com"},
}
ALL_OFFICIAL_DOMAINS = set().union(*BRAND_OFFICIAL_DOMAINS.values())


def registrable_domain(host: str) -> Tuple[str, str]:
    """Return (registrable_domain, registrable_label), e.g. careers.tcs-x.co.in -> (tcs-x.co.in, tcs-x)."""
    labels = host.split(".")
    if len(labels) >= 3 and ".".join(labels[-2:]) in MULTI_LABEL_SUFFIXES:
        reg = labels[-3:]
    else:
        reg = labels[-2:]
    return ".".join(reg), reg[0]


def find_lookalike(host: str) -> Optional[str]:
    """Return an explanation if the domain imitates a known brand, else None."""
    reg, label = registrable_domain(host)
    if reg in ALL_OFFICIAL_DOMAINS:
        return None
    tokens = [t for t in re.split(r"[-_]", label) if t]
    for brand, official in BRAND_OFFICIAL_DOMAINS.items():
        official_list = ", ".join(sorted(official))
        if label == brand:
            return f"'{reg}' uses the brand name '{brand}' but is not an official domain ({official_list})"
        if len(tokens) > 1 and brand in tokens:
            return f"'{reg}' embeds the brand '{brand}' with extra words; official domain(s): {official_list}"
        # Typosquat: edit distance 1 for 5-7 char brands, 1-2 for 8+ char brands.
        # (Shorter brands are handled by the exact/token rules above only.)
        if len(brand) >= 5:
            max_d = 1 if len(brand) <= 7 else 2
            for candidate in {label, *tokens}:
                d = Levenshtein.distance(candidate, brand)
                if 1 <= d <= max_d:
                    return (f"'{reg}' is {d} character(s) away from the brand '{brand}' "
                            f"(possible typosquat); official domain(s): {official_list}")
    return None


def _txt_records(name: str) -> Tuple[Optional[List[str]], Optional[str]]:
    """Return (records, error). error is 'missing' or 'unavailable'."""
    try:
        answers = _resolver.resolve(name, "TXT")
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return None, "missing"
    except (dns.exception.Timeout, dns.resolver.NoNameservers, dns.exception.DNSException):
        return None, "unavailable"
    out = []
    for rdata in answers:
        try:
            out.append(b"".join(rdata.strings).decode("utf-8", errors="ignore"))
        except Exception:
            continue
    return out, None


def check_mx_records(domain: str) -> Dict[str, Any]:
    try:
        answers = _resolver.resolve(domain, "MX")
        if len(answers) > 0:
            return {"check_name": "mx_records", "status": "pass",
                    "explanation": f"'{domain}' publishes {len(answers)} MX record(s)."}
        return {"check_name": "mx_records", "status": "fail",
                "explanation": f"'{domain}' publishes no MX records, so it cannot receive email."}
    except dns.resolver.NXDOMAIN:
        return {"check_name": "mx_records", "status": "fail",
                "explanation": f"'{domain}' does not exist in DNS (NXDOMAIN)."}
    except dns.resolver.NoAnswer:
        return {"check_name": "mx_records", "status": "fail",
                "explanation": f"'{domain}' publishes no MX records, so it cannot receive email."}
    except Exception as e:
        return {"check_name": "mx_records", "status": "unknown",
                "explanation": f"MX lookup for '{domain}' could not be completed ({type(e).__name__})."}


def check_spf_record(domain: str) -> Dict[str, Any]:
    records, err = _txt_records(domain)
    if records and any(r.startswith("v=spf1") for r in records):
        return {"check_name": "spf_record", "status": "pass", "explanation": f"'{domain}' publishes an SPF record."}
    if err == "unavailable":
        return {"check_name": "spf_record", "status": "unknown", "explanation": f"SPF lookup for '{domain}' failed."}
    return {"check_name": "spf_record", "status": "warning", "explanation": f"'{domain}' publishes no SPF record."}


def check_dmarc_record(domain: str) -> Dict[str, Any]:
    records, err = _txt_records(f"_dmarc.{domain}")
    if records and any(r.startswith("v=DMARC1") for r in records):
        return {"check_name": "dmarc_record", "status": "pass", "explanation": f"'{domain}' publishes a DMARC policy."}
    if err == "unavailable":
        return {"check_name": "dmarc_record", "status": "unknown", "explanation": f"DMARC lookup for '{domain}' failed."}
    return {"check_name": "dmarc_record", "status": "warning", "explanation": f"'{domain}' publishes no DMARC policy."}


def _whois_creation_date(domain: str) -> Optional[datetime]:
    """Return the WHOIS creation date, or None if it cannot be determined."""
    try:
        import whois  # python-whois
        w = whois.whois(domain)
        created = w.creation_date
        if isinstance(created, list):
            created = min(c for c in created if isinstance(c, datetime)) if created else None
        return created if isinstance(created, datetime) else None
    except Exception:
        return None


def check_domain_age(domain: str) -> Dict[str, Any]:
    created = _whois_creation_date(domain)
    if created is None:
        return {"check_name": "domain_age", "status": "unknown",
                "explanation": f"Registration age of '{domain}' is unknown (WHOIS lookup failed or returned no date)."}
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    age_days = (datetime.now(timezone.utc) - created).days
    if age_days < MIN_DOMAIN_AGE_DAYS:
        return {"check_name": "domain_age", "status": "fail",
                "explanation": f"'{domain}' was registered only {age_days} day(s) ago."}
    return {"check_name": "domain_age", "status": "pass",
            "explanation": f"'{domain}' was registered {age_days} days ago."}


def _demo_fixture_domains() -> set:
    raw = os.getenv("DEMO_FIXTURE_DOMAINS", "")
    return {d.strip().lower() for d in raw.split(",") if d.strip()}


def _result(status: str, domain: Optional[str], details: str, sub_checks: List[Dict[str, Any]],
            warnings: Optional[List[str]] = None) -> Dict[str, Any]:
    score = {"pass": 95.0, "fail": 25.0}.get(status)
    return {
        "check_name": "domain_verification",
        "status": status,
        "domain": domain,
        "score": score,
        "confidence": 0.9 if status in ("pass", "fail") else 0.0,
        "explanation": details,
        "details": details,
        "warnings": warnings or [],
        "sub_checks": sub_checks,
        "scope": "claimed_domain_in_text",
    }


def _resolve_input_domain(input_data: Union[Dict[str, Any], str, None]) -> Optional[str]:
    if isinstance(input_data, str):
        return input_data.strip() or None
    if isinstance(input_data, dict):
        domain = get_field_value(input_data, "sender_domain", "domain")
        if not domain:
            email_val = get_field_value(input_data, "sender_email")
            if email_val and "@" in email_val:
                domain = email_val.split("@")[-1].strip() or None
        return domain
    return None


def verify_domain(input_data: Union[Dict[str, Any], str, None]) -> Dict[str, Any]:
    """Verify the contact domain claimed in the offer text. See module docstring."""
    domain = _resolve_input_domain(input_data)

    if not domain:
        return _result("not_applicable", None,
                       "No contact email or website domain was found in the offer text.", [])

    host = re.sub(r"^https?://", "", str(domain).strip().lower()).split("/")[0].split(":")[0]
    host = host.removeprefix("www.").rstrip(".")

    if not HOSTNAME_RE.match(host):
        return _result("insufficient_information", None,
                       "The contact domain in the text is not a valid hostname; no lookup was made.", [])

    if is_free_mailbox(host):
        return _result("fail", host,
                       f"Contact address uses the free mailbox provider '{host}', not a company domain.",
                       [{"check_name": "free_mailbox", "status": "fail",
                         "explanation": f"'{host}' is a free/public mailbox provider."}])

    if is_disposable_mailbox(host):
        return _result("fail", host,
                       f"Contact address uses the disposable (temporary) mailbox service '{host}'; "
                       "companies do not send offers from these.",
                       [{"check_name": "disposable_mailbox", "status": "fail",
                         "explanation": f"'{host}' is a throwaway mailbox service."}])

    lookalike = find_lookalike(host)
    if lookalike:
        return _result("fail", host, f"Lookalike domain: {lookalike}.",
                       [{"check_name": "brand_lookalike", "status": "fail", "explanation": lookalike}])

    reg_domain, _ = registrable_domain(host)
    claimed = get_field_value(input_data, "company_name", "company_name_legacy") if isinstance(input_data, dict) else None
    mismatch = brand_advisories.official_domain_mismatch(claimed, reg_domain)
    if mismatch:
        return _result("fail", host, mismatch,
                       [{"check_name": "employer_official_domain", "status": "fail", "explanation": mismatch}])
    if os.getenv("DEMO_MODE") == "1" and (host in _demo_fixture_domains() or reg_domain in _demo_fixture_domains()):
        logger.warning("[DOMAIN_VERIFY] DEMO_MODE fixture applied; result is not a live DNS lookup.")
        return _result("pass", host,
                       f"{DEMO_PREFIX} '{host}' is a configured demo fixture domain; MX/SPF/DMARC/WHOIS were not queried.",
                       [{"check_name": "demo_fixture", "status": "pass", "explanation": DEMO_PREFIX}])

    mx = check_mx_records(host)
    if mx["status"] == "unknown":
        return _result("insufficient_information", host,
                       f"DNS was unavailable, so '{host}' could not be checked. " + mx["explanation"], [mx])
    if mx["status"] == "fail":
        return _result("fail", host, mx["explanation"], [mx])

    spf = check_spf_record(host)
    dmarc = check_dmarc_record(host)
    age = check_domain_age(reg_domain)
    sub_checks = [mx, spf, dmarc, age]

    if age["status"] == "fail":
        return _result("fail", host, f"Newly registered domain: {age['explanation']}", sub_checks)

    warnings = [c["explanation"] for c in (spf, dmarc, age) if c["status"] in ("warning", "unknown")]
    details = f"Claimed contact domain '{host}' exists and accepts email (MX present)."
    if warnings:
        details += " Warnings: " + " ".join(warnings)
    if age["status"] in ("warning", "unknown"):
        first_seen = web_archive.first_capture_month(reg_domain)
        if first_seen:
            details += (f" The Internet Archive's earliest saved copy of '{reg_domain}' is from {first_seen} "
                        "(informational only; it does not show who sent this offer).")
    details += " Note: this checks the domain written in the text, not the actual sender."
    return _result("pass", host, details, sub_checks, warnings)
