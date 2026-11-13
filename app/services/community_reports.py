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
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.models import (CommunityDispute, CommunityIndicator, CommunityReport,
    CommunityTemplateBand, CommunityToken)
from app.services import payment_detection
from app.utils.email_domains import is_free_mailbox, is_upi_handle

CONSENT_VERSION = 2
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


def masked(kind: str, value: str) -> str:
    if kind == "upi":
        local, handle = value.split("@", 1)
        return local[:7] + "•••@" + handle
    if kind == "email":
        local, domain = value.split("@", 1)
        return local[:2] + "•••@" + domain
    if kind == "phone":
        digits = re.sub(r"\D", "", value)
        return "+91 ••••••" + digits[-4:]
    if kind == "bank":
        account, ifsc = value.split("|", 1)
        return "••••" + account[-4:] + " + " + ifsc
    labels = value.split(".")
    return labels[0][:2] + "•••." + labels[-1]


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
    text = EMAIL_RE.sub("<EMAIL>", text)
    text = VPA_RE.sub("<UPI>", text)
    text = IFSC_RE.sub("<IFSC>", text)
    text = ACCOUNT_RE.sub("<ACCOUNT>", text)
    text = PHONE_RE.sub("<PHONE>", text)
    text = re.sub(r"(?i)(?:₹|INR|Rs\.?\s*)\s*[\d,]+(?:\.\d{1,2})?", "<AMOUNT>", text)
    text = re.sub(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b", "<DATE>", text)
    text = re.sub(r"(?im)\b(?:candidate|applicant|student)\b[^\n]{0,60}", "<CANDIDATE>", text)
    return text


def minhash_signature(text: str) -> list[int]:
    words = re.findall(r"[a-z0-9<>]+", redact_text(text).casefold())
    shingles = [" ".join(words[i:i + 5]) for i in range(max(0, len(words) - 4))]
    if not shingles:
        shingles = ["<EMPTY>"]
    hashes = [int.from_bytes(hashlib.sha256(s.encode()).digest()[:8], "big") for s in shingles]
    return [min((h ^ ((i + 1) * 0x9E3779B97F4A7C15)) & 0xFFFFFFFFFFFFFFFF for h in hashes)
            for i in range(MINHASH_SIZE)]


def _signature_bands(signature: list[int]):
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


def issue_report_token(db: Session, indicators: list[dict], signature: list[int]):
    current, _ = _pepper_config()
    if not current or not signature:
        return None, []
    version, pepper = current
    jti = str(uuid.uuid4())
    expires = _utcnow() + timedelta(hours=24)
    token_indicators = [{k: item[k] for k in ("indicator_type", "digest", "key_version", "masked")}
                        for item in indicators]
    payload = {"jti": jti, "exp": int(expires.timestamp()), "consent_version": CONSENT_VERSION,
               "indicators": token_indicators, "signature": signature}
    db.add(CommunityToken(jti=jti, expires_at=expires))
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
    jti = payload["jti"]
    code = secrets.token_urlsafe(24)
    report_id = str(uuid.uuid4())
    signature = payload["signature"]
    report = CommunityReport(id=report_id, consent_version=CONSENT_VERSION,
        signature=json.dumps(signature), created_at=now, last_seen_at=now,
        withdrawal_code_hash=hashlib.sha256(code.encode()).hexdigest(), is_demo=os.getenv("DEMO_MODE") == "1")
    db.add(report)
    for digest in set(selected):
        item = by_id[digest]
        db.add(CommunityIndicator(report_id=report_id, indicator_type=item["indicator_type"],
            digest=item["digest"], key_version=item["key_version"], created_at=now, last_seen_at=now))
    for band, bucket in _signature_bands(signature):
        db.add(CommunityTemplateBand(report_id=report_id, band=band, bucket=bucket))
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
    total_points = 0
    notes = []
    now = _utcnow()
    demo_only = os.getenv("DEMO_MODE") == "1"
    for item in indicators:
        matches = []
        for version, pepper in peppers.items():
            digest = _digest(item["indicator_type"], item["normalized_value"], pepper)
            matches.extend(db.query(CommunityIndicator).filter_by(indicator_type=item["indicator_type"], digest=digest, key_version=version).all())
        reports = {m.report_id for m in matches if (demo_only or not m.report.is_demo) and not m.report.withdrawn}
        if not reports:
            continue
        disputes = []
        for version, pepper in peppers.items():
            digest = _digest(item["indicator_type"], item["normalized_value"], pepper)
            dispute = db.query(CommunityDispute).filter_by(indicator_type=item["indicator_type"], digest=digest,
                key_version=version, resolved_at=None).first()
            if dispute:
                disputes.append(dispute)
        if disputes and not (item["indicator_type"] == "domain" and any(x.domain_verified for x in disputes)):
            notes.append("An indicator match is disputed by the company, under review.")
        if item["indicator_type"] == "domain" and any(x.domain_verified for x in disputes):
            continue
        count = len(reports)
        if count >= 10:
            total_points += 40
            notes.append(f"This {item['indicator_type']} appears in reports from 10+ students.")
        elif count >= 3:
            total_points += 25
            notes.append(f"This {item['indicator_type']} appears in reports from 3+ students.")
        for report_id in reports:
            db.query(CommunityReport).filter_by(id=report_id).update({"last_seen_at": now})
            db.query(CommunityIndicator).filter_by(report_id=report_id, digest=item["digest"]).update({"last_seen_at": now})

    candidate_ids = {row.report_id for band, bucket in _signature_bands(signature)
                     for row in db.query(CommunityTemplateBand).filter_by(band=band, bucket=bucket)}
    for report in db.query(CommunityReport).filter(CommunityReport.id.in_(candidate_ids), CommunityReport.withdrawn.is_(False)).all() if candidate_ids else []:
        if not demo_only and report.is_demo:
            continue
        old_signature = json.loads(report.signature)
        score = similarity(signature, old_signature)
        if score >= 0.8:
            total_points += 25
            notes.append("This letter wording is similar to a reported scam template.")
            report.last_seen_at = now
            break
    db.commit()
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
    db.commit()


def stats(db: Session):
    query = db.query(CommunityIndicator.indicator_type, func.count(func.distinct(CommunityIndicator.report_id))).join(
        CommunityReport).filter(CommunityReport.withdrawn.is_(False))
    if os.getenv("DEMO_MODE") != "1":
        query = query.filter(CommunityReport.is_demo.is_(False))
    rows = query.group_by(CommunityIndicator.indicator_type).all()
    return {"indicators": [{"indicator_type": kind, "reports": count if count >= 5 else None,
                             "suppressed": count < 5} for kind, count in rows]}
