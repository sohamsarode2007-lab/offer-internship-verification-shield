"""Parse original RFC 5322 .eml uploads and assess provider-added auth results.

Headers are processed only in memory. Never log, persist, or return raw headers,
addresses, IPs, display names, or Authentication-Results values. Public details
are restricted to the sender domain and sanitized check findings.
"""
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
from html.parser import HTMLParser
import re
from typing import Any, Dict, List, Optional

from app.services.domain_verification import BRAND_OFFICIAL_DOMAINS, HOSTNAME_RE, registrable_domain
from app.utils.email_domains import is_free_mailbox


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: List[str] = []

    def handle_data(self, data):
        if data.strip():
            self.parts.append(data.strip())


def _address_domain(value: Optional[str]) -> tuple[Optional[str], str]:
    display, address = parseaddr(str(value or ""))
    if "@" not in address:
        return None, display
    domain = address.rsplit("@", 1)[1].strip().lower().rstrip(">")
    return (domain if HOSTNAME_RE.fullmatch(domain) else None), display


def parse_eml(file_bytes: bytes) -> Dict[str, Any]:
    """Extract body, file attachments and minimal parsed sender metadata."""
    try:
        message = BytesParser(policy=policy.default).parsebytes(file_bytes)
    except Exception as exc:
        raise ValueError("email message could not be parsed") from exc
    body = ""
    try:
        body_part = message.get_body(preferencelist=("plain",))
        if body_part is None:
            body_part = message.get_body(preferencelist=("html",))
            if body_part is not None:
                parser = _HTMLText()
                parser.feed(body_part.get_content())
                body = "\n".join(parser.parts)
        elif body_part is not None:
            body = body_part.get_content()
    except (LookupError, UnicodeError, ValueError) as exc:
        raise ValueError("email body could not be decoded") from exc
    attachments = []
    for part in message.iter_attachments():
        content_type = part.get_content_type().lower()
        filename = part.get_filename() or "attachment"
        extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if content_type == "application/pdf" or extension == "pdf":
            allowed = "pdf"
        elif content_type.startswith("image/") or extension in {"png", "jpg", "jpeg", "bmp", "tiff"}:
            allowed = extension if extension in {"png", "jpg", "jpeg", "bmp", "tiff"} else content_type.split("/", 1)[1]
            if allowed == "jpeg":
                allowed = "jpg"
            if allowed not in {"png", "jpg", "bmp", "tiff"}:
                continue
        else:
            continue
        data = part.get_payload(decode=True)
        if data:
            attachments.append({"filename": f"email-attachment.{allowed}", "content_type": content_type, "data": data})
    from_domain, display_name = _address_domain(message.get("From"))
    _, from_address = parseaddr(str(message.get("From") or ""))
    sender_email = from_address.strip().lower() if "@" in from_address else None
    reply_domain, _ = _address_domain(message.get("Reply-To"))
    auth_headers = message.get_all("Authentication-Results", [])
    top = str(auth_headers[0]) if auth_headers else ""
    authserv_tokens = top.split(";", 1)[0].strip().split()
    authserv_id = authserv_tokens[0] if authserv_tokens else None
    return {"body_text": body, "attachments": attachments, "sender_domain": from_domain,
            "sender_email": sender_email,
            "display_name": display_name, "reply_domain": reply_domain,
            "authserv_id": authserv_id, "auth_headers": [str(h) for h in auth_headers]}


def _result(status: str, domain: Optional[str], points: int, details: str, **meta) -> Dict[str, Any]:
    return {"check_name": "sender_authentication", "status": status,
            "sender_domain": domain, "risk_points": points,
            "details": details, "explanation": details, **meta}


def not_applicable() -> Dict[str, Any]:
    return _result("not_applicable", None, 0,
                   "Upload the original .eml email to check its actual sender and provider authentication results.")


def _auth_signature(header: str):
    spf = re.search(r"\bspf=(pass|fail|softfail|neutral|none|temperror|permerror)\b", header, re.I)
    dkim = re.search(r"\bdkim=(pass|fail|policy|neutral|none|temperror|permerror)\b([^;]*)", header, re.I)
    dmarc = re.search(r"\bdmarc=(pass|fail|bestguesspass|none|temperror|permerror)\b", header, re.I)
    d_value = None
    if dkim:
        d_match = re.search(r"\bheader\.d=([^\s;]+)", dkim.group(2), re.I)
        candidate = d_match.group(1).strip("<>").lower().rstrip(".") if d_match else None
        d_value = candidate if candidate and HOSTNAME_RE.fullmatch(candidate) else None
    dmarc_status = dmarc.group(1).lower() if dmarc else None
    if dmarc_status == "none":
        dmarc_status = None
    return (spf.group(1).lower() if spf else None,
            dkim.group(1).lower() if dkim else None,
            d_value,
            dmarc_status)


def verify_sender_authentication(parsed: Dict[str, Any], body_facts: Dict[str, Any]) -> Dict[str, Any]:
    domain = parsed.get("sender_domain")
    headers = parsed.get("auth_headers") or []
    has_auth_results = bool(headers)
    spf_status, dkim_status, d_value, dmarc_status = _auth_signature(headers[0]) if headers else (None, None, None, None)
    aligned = bool(domain and d_value and registrable_domain(domain)[0] == registrable_domain(d_value)[0])
    signals: List[str] = []
    points = 0
    hard_auth_fail = dmarc_status == "fail" or (dmarc_status is None and spf_status == "fail" and dkim_status == "fail")
    if hard_auth_fail:
        points += 30
        signals.append("provider authentication failed (+30)")

    reply_domain = parsed.get("reply_domain")
    if domain and reply_domain and not is_free_mailbox(domain):
        unrelated_reply = is_free_mailbox(reply_domain) or registrable_domain(domain)[0] != registrable_domain(reply_domain)[0]
        if unrelated_reply:
            points += 25
            signals.append("Reply-To is a free-mailbox or unrelated domain (+25)")

    display = (parsed.get("display_name") or "").lower()
    brands = [brand for brand in BRAND_OFFICIAL_DOMAINS
              if re.search(rf"(?<![a-z0-9]){re.escape(brand)}(?![a-z0-9])", display)]
    registered_from = registrable_domain(domain)[0] if domain else None
    if any(not registered_from or registered_from not in BRAND_OFFICIAL_DOMAINS[brand] for brand in brands):
        points += 25
        signals.append("display name uses a protected brand outside its official domain (+25)")

    body_domain_value = body_facts.get("sender_domain")
    body_domain = body_domain_value.get("value") if isinstance(body_domain_value, dict) else body_domain_value
    body_host = str(body_domain).strip().lower().rstrip(".") if body_domain else None
    sender_host = domain.strip().lower().rstrip(".") if domain else None
    if (body_host and sender_host
            and registrable_domain(body_host)[0] != registrable_domain(sender_host)[0]):
        points += 15
        signals.append("domain claimed in the letter differs from the authenticated From domain (+15)")

    if dmarc_status == "pass" and aligned:
        signals.append("DMARC passed and DKIM is aligned (−10)")
    lower_disagrees = any(_auth_signature(header) != (spf_status, dkim_status, d_value, dmarc_status)
                          for header in headers[1:])
    if lower_disagrees:
        signals.append("lower Authentication-Results headers disagree and were ignored as untrusted")
    if not has_auth_results:
        status = "insufficient_information"
    elif hard_auth_fail or points > 0:
        status = "fail"
    elif dmarc_status == "pass" and aligned:
        status = "pass"
    else:
        status = "insufficient_information"
    no_header_note = "No Authentication-Results header (forwarded or exported without headers). " if not has_auth_results else ""
    details = no_header_note + f"Sender domain: {domain or 'unknown'}. " + (
        "; ".join(signals) if signals else "No decisive provider-authentication result.")
    return _result(status, domain, points, details,
        authserv_id=parsed.get("authserv_id"), spf_status=spf_status,
        dkim_status=dkim_status, dkim_domain=d_value, dkim_aligned=aligned,
        dmarc_status=dmarc_status, has_auth_results=has_auth_results,
        lower_auth_results_disagree=lower_disagrees, response_details=details)
