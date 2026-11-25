"""Privacy-preserving community indicator extraction, tokens, and matching."""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session, joinedload

from app.models.models import (CommunityDispute, CommunityIndicator, CommunityReport,
    CommunityTemplateBand, CommunityToken)
from app.services import payment_detection
from app.services import upi_payment
from app.utils.email_domains import is_free_mailbox, is_upi_handle

CONSENT_VERSION = 4  # v4: details appear in masked form on the public scam-trends page (v3 named one college)
# Independence is not provable without identifying reporters, so the only gate is a weak one: reports for the same
# indicator must span at least this many different UTC days before they count (one burst in one sitting never does).
MIN_DISTINCT_DAYS = 2
DISPUTE_ACTIVE_DAYS = 90        # an unresolved dispute affects results for this long, then lapses
DISPUTE_KEEP_DAYS = 180         # and is deleted (with its contact email) after this long
ANALYSIS_RETENTION_DAYS = 365   # stored analysis results (and their per-check rows) are deleted after this long
MAX_ACTIVE_DISPUTES_PER_EMAIL = 3
MAX_ACTIVE_DISPUTES_PER_INDICATOR = 5
MINHASH_SIZE = 128
BAND_SIZE = 8
PHONE_RE = re.compile(r"(?<!\w)(?:\+?91[\s().-]?)?[6-9]\d{9}(?!\w)")
VPA_RE = re.compile(r"\b[A-Za-z0-9._-]{2,}@[A-Za-z0-9.-]+\b")
ACCOUNT_RE = re.compile(r"\b\d{9,18}\b")
IFSC_RE = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b", re.I)
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
CONTACT_RE = re.compile(r"\b(?:call|whats\s?app|contact|reach|hr|phone|mobile|email)\b", re.I)
RECIPIENT_RE = re.compile(r"^\s*(?:to|cc|bcc)\s*:|^\s*dear\b", re.I)
PAYMENT_CONTEXT_RE = re.compile(r"\b(?:pay|payment|transfer|send|deposit|fee|account|upi|remit|beneficiary)\b", re.I)


def _utcnow():
    return datetime.now(timezone.utc)


def spans_enough_days(created_times) -> bool:
    """True when the reports were made on at least MIN_DISTINCT_DAYS different UTC days."""
    return len({t.date() for t in created_times if t is not None}) >= MIN_DISTINCT_DAYS


def active_dispute_cutoff(now: datetime | None = None) -> datetime:
    return (now or _utcnow()) - timedelta(days=DISPUTE_ACTIVE_DAYS)


def _pepper_config():
    current = os.getenv("INDICATOR_PEPPER")
    if not current:
        return None, {}
    version = int(os.getenv("INDICATOR_KEY_VERSION", "1"))
    old = {}
    for part in os.getenv("INDICATOR_PEPPER_PREVIOUS", "").split(","):
        if ":" in part:
            ver, secret = part.split(":", 1)
            if ver.isdigit() and secret:
                old[int(ver)] = secret
    return (version, current), old


def _digest(kind: str, value: str, pepper: str) -> str:
    normalized = normalize(kind, value)
    return hmac.new(pepper.encode(), f"indicator:{kind}:{normalized}".encode(), hashlib.sha256).hexdigest()


def normalize(kind: str, value: str) -> str:
    value = value.strip().casefold()
    if kind in {"upi", "email", "domain"}:
        return value.rstrip(".")
    if kind == "phone":
        digits = re.sub(r"\D", "", value)
        if len(digits) == 10:
            digits = "91" + digits
        return "+" + digits
    if kind == "bank":
        account, ifsc = value.split("|", 1)
        return re.sub(r"\D", "", account) + "|" + re.sub(r"\s", "", ifsc).upper()
    return value


def _visible_prefix(local: str, cap: int) -> str:
    """The first `cap` characters (as in the report flow), but always hide at least one,
    so a short local part is never shown in full."""
    return local[:max(1, min(cap, len(local) - 1))]


def masked(kind: str, value: str) -> str:
    """Display form shown in the report flow and on the scam-trends page.

    Never the full value, except a sender domain: domain indicators are only
    extracted for non-free-mail domains, and those are shown in full."""
    if kind == "upi":
        local, handle = value.split("@", 1)
        return _visible_prefix(local, 7) + "•••@" + handle
    if kind == "email":
        local, domain = value.split("@", 1)
        return _visible_prefix(local, 2) + "•••@" + domain.casefold()
    if kind == "phone":
        digits = re.sub(r"\D", "", value)
        return "+91 ••••••" + digits[-4:]
    if kind == "bank":
        account, ifsc = value.split("|", 1)
        return "••••" + account[-4:] + " + " + ifsc.upper()
    return value.strip().casefold().rstrip(".")


def _contact_line(line: str) -> bool:
    return bool(CONTACT_RE.search(line)) and not RECIPIENT_RE.search(line) and not re.search(
        r"\b(?:candidate|applicant|student|my details|your details|personal details)\b", line, re.I)


def extract_indicators(text: str, parsed_email: dict | None, payment_check: dict) -> list[dict]:
    """Only return scammer-role addresses, demand payment destinations, and contact phones."""
    found: dict[tuple[str, str], str] = {}
    def add(kind, value):
        value = value.strip().rstrip(".,;:")
        if kind == "upi" and not is_upi_handle(value.rsplit("@", 1)[-1].lower()):
            return
        if kind == "domain" and is_free_mailbox(value):
            return
        key = (kind, normalize(kind, value))
        found[key] = value

    if parsed_email:
        sender_email = parsed_email.get("sender_email")
        sender_domain = parsed_email.get("sender_domain")
        if sender_email:
            add("email", sender_email)
        if sender_domain:
            add("domain", sender_domain)
    else:
        for line in text.splitlines():
            if not _contact_line(line):
                continue
            for m in EMAIL_RE.finditer(line):
                address = m.group(0)
                if not is_upi_handle(address.rsplit("@", 1)[-1].lower()):
                    add("email", address)
                    add("domain", address.rsplit("@", 1)[-1])

    if payment_check.get("status") == "fail":
        spans = payment_detection.sentence_spans(text)
        demand_spans = payment_detection._find_phrase_demands(text, spans)
        demand_spans += payment_detection._find_upi_demands(text, spans)
        for match in VPA_RE.finditer(text):
            if not is_upi_handle(match.group(0).rsplit("@", 1)[-1].lower()):
                continue
            if any(max(d["start"] - match.end(), match.start() - d["end"], 0) <= 200 for d in demand_spans):
                add("upi", match.group(0))
        for request in upi_payment.find_upi_requests(text):
            if request["vpa"]:  # a upi:// payload is a payment destination whatever the handle
                found[("upi", normalize("upi", request["vpa"]))] = request["vpa"]
        for line in text.splitlines():
            if not PAYMENT_CONTEXT_RE.search(line):
                continue
            ifscs = list(IFSC_RE.finditer(line))
            accounts = list(ACCOUNT_RE.finditer(line))
            for account in accounts:
                matching_ifsc = next((i for i in ifscs if abs(i.start() - account.end()) <= 100), None)
                if matching_ifsc:
                    add("bank", account.group(0) + "|" + matching_ifsc.group(0))

    for line in text.splitlines():
        if not _contact_line(line):
            continue
        for phone in PHONE_RE.finditer(line):
            add("phone", phone.group(0))

    current, _ = _pepper_config()
    if not current:
        return []
    version, pepper = current
    return [{"indicator_type": kind, "digest": _digest(kind, value, pepper),
             "key_version": version, "masked": masked(kind, value), "normalized_value": normalize(kind, value)}
            for (kind, _), value in found.items()]


def redact_text(text: str) -> str:
    text = re.sub(r"(?im)(\b(?:candidate|applicant|student)?\s*name\s*[:=-]\s*)[^\n,;]+", r"\1<NAME>", text)
    text = re.sub(r"(?im)^\s*dear\s+[^,\n]+", "Dear <NAME>", text)
    text = upi_payment.UPI_URI_RE.sub("<UPI_LINK>", text)
    text = EMAIL_RE.sub("<EMAIL>", text)
    text = VPA_RE.sub("<UPI>", text)
    text = IFSC_RE.sub("<IFSC>", text)
    text = ACCOUNT_RE.sub("<ACCOUNT>", text)
    text = PHONE_RE.sub("<PHONE>", text)
    text = re.sub(r"(?i)(?:₹|INR|Rs\.?\s*)\s*[\d,]+(?:\.\d{1,2})?", "<AMOUNT>", text)
    text = re.sub(r"(?i)\b(?:salary|stipend|amount|fee|deposit|pay|paid|cost|compensation)\s*(?:is|of|:|=)?\s*[\d,]+(?:\.\d{1,2})?\b", "<AMOUNT>", text)
    text = re.sub(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b", "<DATE>", text)
    text = re.sub(r"(?im)\b(?:candidate|applicant|student)\b[^\n]{0,60}", "<CANDIDATE>", text)
    return text


def minhash_signature(text: str) -> list[int]:
    words = re.findall(r"[a-z0-9<>]+", redact_text(text).casefold())
    shingles = [" ".join(words[i:i + 5]) for i in range(max(0, len(words) - 4))]
    if not shingles:
        return []
    hashes = [int.from_bytes(hashlib.sha256(s.encode()).digest()[:8], "big") for s in shingles]
    return [min((h ^ ((i + 1) * 0x9E3779B97F4A7C15)) & 0xFFFFFFFFFFFFFFFF for h in hashes)
            for i in range(MINHASH_SIZE)]


def _signature_bands(signature: list[int]):
    if len(signature) != MINHASH_SIZE:
        return []
    return [(band, hashlib.sha256(",".join(map(str, signature[band * BAND_SIZE:(band + 1) * BAND_SIZE])).encode()).hexdigest())
            for band in range(MINHASH_SIZE // BAND_SIZE)]


def similarity(left: list[int], right: list[int]) -> float:
    if len(left) != MINHASH_SIZE or len(right) != MINHASH_SIZE:
        return 0.0
    return sum(a == b for a, b in zip(left, right)) / MINHASH_SIZE


def _sign_payload(payload: dict, pepper: str) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()).decode().rstrip("=")
    signature = hmac.new(pepper.encode(), ("report-token:" + body).encode(), hashlib.sha256).hexdigest()
    return body + "." + signature


def _decode_token(token: str, pepper: str) -> dict:
    try:
        body, signature = token.split(".", 1)
        expected = hmac.new(pepper.encode(), ("report-token:" + body).encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise ValueError
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        return payload
    except Exception as exc:
        raise ValueError("invalid report token") from exc


def issue_report_token(db: Session, indicators: list[dict], signature: list[int],
                       band: str | None = None, scam_category: str | None = None):
    """Signed, single-use token. band/scam_category (rule outputs, no text) let a consented
    report be counted on the scam-trends dashboard."""
    current, _ = _pepper_config()
    if not current or (not signature and not indicators):
        return None, []
    version, pepper = current
    jti = str(uuid.uuid4())
    expires = _utcnow() + timedelta(hours=24)
    token_indicators = [{k: item[k] for k in ("indicator_type", "digest", "key_version", "masked")}
                        for item in indicators]
    payload = {"jti": jti, "exp": int(expires.timestamp()), "consent_version": CONSENT_VERSION,
               "indicators": token_indicators, "signature": signature,
               "band": band, "scam_category": scam_category}
    db.add(CommunityToken(jti=jti, expires_at=expires))
    db.flush()
    return _sign_payload(payload, pepper), [{"id": x["indicator_type"] + ":" + x["digest"], "indicator_type": x["indicator_type"], "masked": x["masked"]} for x in indicators]


def accept_report(db: Session, token: str, selected: list[str], consent: bool, consent_version: int):
    if not consent or consent_version != CONSENT_VERSION:
        raise ValueError("current consent is required")
    current, _ = _pepper_config()
    if not current:
        raise ValueError("community reports are unavailable")
    payload = _decode_token(token, current[1])
    now = _utcnow()
    if payload.get("consent_version") != CONSENT_VERSION or payload.get("exp", 0) <= now.timestamp():
        raise ValueError("report token expired or invalid")
    consumed = db.query(CommunityToken).filter(CommunityToken.jti == payload["jti"],
        CommunityToken.consumed_at.is_(None), CommunityToken.expires_at > now).update(
            {"consumed_at": now}, synchronize_session=False)
    if consumed != 1:
        raise ValueError("report token expired or already used")
    by_id = {x["indicator_type"] + ":" + x["digest"]: x for x in payload["indicators"]}
    if not set(selected).issubset(by_id):
        raise ValueError("selected indicators were not offered by this analysis")
    code = secrets.token_urlsafe(24)
    report_id = str(uuid.uuid4())
    signature = payload["signature"]
    report = CommunityReport(id=report_id, consent_version=CONSENT_VERSION,
        signature=json.dumps(signature), created_at=now, last_seen_at=now,
        withdrawal_code_hash=hashlib.sha256(code.encode()).hexdigest(), is_demo=False)
    db.add(report)
    from app.services.institution_dashboard import current_iso_week
    week = current_iso_week(now.date())
    category = payload.get("scam_category") or "other"
    for digest in set(selected):
        item = by_id[digest]
        # The token carries only the masked display form, never the raw value.
        db.add(CommunityIndicator(report_id=report_id, indicator_type=item["indicator_type"],
            digest=item["digest"], key_version=item["key_version"], created_at=now, last_seen_at=now,
            masked_display=item.get("masked"), iso_week=week, scam_category=category))
    for band, bucket in _signature_bands(signature):
        db.add(CommunityTemplateBand(report_id=report_id, band=band, bucket=bucket))
    # The check behind this report was already counted once by /analyze; no second trend row.
    db.commit()
    return {"status": "reported", "withdrawal_code": code}


def withdraw_report(db: Session, code: str):
    digest = hashlib.sha256(code.encode()).hexdigest()
    report = db.query(CommunityReport).filter_by(withdrawal_code_hash=digest, withdrawn=False).first()
    if not report:
        raise ValueError("invalid or already-used withdrawal code")
    report.withdrawn = True
    db.delete(report)
    db.commit()
    return {"status": "withdrawn"}


def lookup_community(db: Session, indicators: list[dict], signature: list[int]):
    current, previous = _pepper_config()
    if not current:
        return {"check_name": "community_reports", "status": "not_applicable", "score": 0,
                "details": "Community report matching is unavailable until INDICATOR_PEPPER is configured."}
    peppers = {current[0]: current[1], **previous}
    indicator_bucket_points = 0
    template_points = 0
    notes = []
    now = _utcnow()
    for item in indicators:
        wanted = [(version, _digest(item["indicator_type"], item["normalized_value"], pepper))
                  for version, pepper in peppers.items()]
        # One query per indicator, with each match's report loaded in the same query (not one query per match).
        matches = db.query(CommunityIndicator).options(joinedload(CommunityIndicator.report)).filter(
            CommunityIndicator.indicator_type == item["indicator_type"],
            or_(*[and_(CommunityIndicator.digest == d, CommunityIndicator.key_version == v) for v, d in wanted]),
        ).all()
        live = [m for m in matches if not m.report.is_demo and not m.report.withdrawn]
        reports = {m.report_id for m in live}
        if not reports:
            continue
        if not spans_enough_days([m.report.created_at for m in live]):
            continue                      # a single day's reports are not counted; see MIN_DISTINCT_DAYS
        disputes = db.query(CommunityDispute).filter(
            CommunityDispute.indicator_type == item["indicator_type"],
            or_(*[and_(CommunityDispute.digest == d, CommunityDispute.key_version == v) for v, d in wanted]),
            CommunityDispute.resolved_at.is_(None),
            CommunityDispute.created_at > active_dispute_cutoff(now)).all()
        if disputes and not (item["indicator_type"] == "domain" and any(x.domain_verified for x in disputes)):
            notes.append("An indicator match is disputed by the company, under review.")
        if item["indicator_type"] == "domain" and any(x.domain_verified for x in disputes):
            continue
        count = len(reports)
        if count >= 10:
            indicator_bucket_points = max(indicator_bucket_points, 40)
            notes.append(f"This {item['indicator_type']} was reported in 10+ separate reports.")
        elif count >= 3:
            indicator_bucket_points = max(indicator_bucket_points, 25)
            notes.append(f"This {item['indicator_type']} was reported in 3+ separate reports.")
        for report_id in reports:
            db.query(CommunityReport).filter_by(id=report_id).update({"last_seen_at": now})
            db.query(CommunityIndicator).filter_by(report_id=report_id, digest=item["digest"]).update({"last_seen_at": now})

    candidate_ids = {row.report_id for band, bucket in _signature_bands(signature)
                     for row in db.query(CommunityTemplateBand).filter_by(band=band, bucket=bucket)}
    for report in db.query(CommunityReport).filter(CommunityReport.id.in_(candidate_ids), CommunityReport.withdrawn.is_(False)).all() if candidate_ids else []:
        if report.is_demo:
            continue
        old_signature = json.loads(report.signature)
        score = similarity(signature, old_signature)
        if score >= 0.8:
            template_points = 25
            notes.append("This letter wording is similar to a reported scam template.")
            report.last_seen_at = now
            break
    db.commit()
    total_points = min(40, indicator_bucket_points + template_points)
    return {"check_name": "community_reports", "status": "fail" if total_points else "pass",
            "score": total_points, "risk_points": total_points,
            "details": " ".join(dict.fromkeys(notes)) if notes else "No matching community scam reports were found."}


def purge_expired(db: Session, now: datetime | None = None):
    now = now or _utcnow()
    cutoff = now - timedelta(days=730)
    db.query(CommunityToken).filter(CommunityToken.expires_at < now - timedelta(hours=48)).delete(synchronize_session=False)
    stale = db.query(CommunityReport).filter(CommunityReport.last_seen_at < cutoff).all()
    for report in stale:
        db.delete(report)
    db.query(CommunityDispute).filter(CommunityDispute.resolved_at.is_not(None),
        CommunityDispute.resolved_at < now - timedelta(days=365)).delete(synchronize_session=False)
    db.query(CommunityDispute).filter(CommunityDispute.created_at < now - timedelta(days=DISPUTE_KEEP_DAYS)
        ).delete(synchronize_session=False)
    # Stored analysis results (score and per-check outcome; never offer text) are not kept forever.
    from app.models.models import Offer
    # ORM delete (not a bulk delete) so the per-check rows go too, whether or not the database enforces foreign keys.
    for old in db.query(Offer).filter(Offer.created_at < now - timedelta(days=ANALYSIS_RETENTION_DAYS)).limit(1000).all():
        db.delete(old)
    from app.services.institution_dashboard import purge_old_observations
    purge_old_observations(db, now.date())
    db.commit()


def stats(db: Session):
    query = db.query(CommunityIndicator.indicator_type, CommunityIndicator.report_id, CommunityReport.created_at).join(
        CommunityReport).filter(CommunityReport.withdrawn.is_(False), CommunityReport.is_demo.is_(False))
    by_kind: dict = {}
    for kind, report_id, created in query.all():
        entry = by_kind.setdefault(kind, {"ids": set(), "times": []})
        entry["ids"].add(report_id)
        entry["times"].append(created)
    out = []
    for kind, entry in by_kind.items():
        count = len(entry["ids"])
        shown = count >= 5 and spans_enough_days(entry["times"])
        out.append({"indicator_type": kind, "reports": count if shown else None, "suppressed": not shown})
    return {"indicators": out}
