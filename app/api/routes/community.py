"""Consent, withdrawal, disputes, and aggregate community indicator endpoints."""
import hashlib
import os
import secrets
import smtplib
from datetime import timedelta
from email.message import EmailMessage

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.limiter import limiter
from app.db.database import get_db
from app.models.models import CommunityDispute
from app.services import community_reports as cr

router = APIRouter(tags=["community"])


class ReportRequest(BaseModel):
    report_token: str = Field(min_length=20, max_length=100000)
    consent: bool
    consent_version: int
    selected_indicators: list[str] = Field(default_factory=list)


class WithdrawRequest(BaseModel):
    code: str = Field(min_length=20, max_length=200)


DisputeReason = Literal["our_business_detail", "reported_in_error", "someone_else_misused_it", "other"]


class DisputeRequest(BaseModel):
    indicator_type: str
    value: str = Field(min_length=3, max_length=320)
    contact_email: str = Field(min_length=5, max_length=320)
    # A fixed code, never free text: free text invited offer letters, names and bank details into the database.
    reason_code: DisputeReason


def _send_verification(email: str, token: str, domain: str):
    host = os.getenv("SMTP_HOST")
    base_url = os.getenv("PUBLIC_BASE_URL")
    if not host or not base_url:
        return False
    message = EmailMessage()
    message["Subject"] = "Verify company-domain dispute"
    message["From"] = os.getenv("SMTP_FROM", "no-reply@localhost")
    message["To"] = email
    message.set_content(f"Verify this domain dispute for {domain}: {base_url.rstrip('/')}/disputes/verify?token={token}\nThis link expires in 24 hours.")
    with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=10) as smtp:
        smtp.starttls()
        username = os.getenv("SMTP_USERNAME")
        if username:
            smtp.login(username, os.getenv("SMTP_PASSWORD", ""))
        smtp.send_message(message)
    return True


@router.post("/report")
@limiter.limit("5/hour")
def report(request: Request, payload: ReportRequest, db: Session = Depends(get_db)):
    cr.purge_expired(db)
    try:
        result = cr.accept_report(db, payload.report_token, payload.selected_indicators,
                                  payload.consent, payload.consent_version)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    return result


@router.post("/report/withdraw")
@limiter.limit("5/hour")
def withdraw(request: Request, payload: WithdrawRequest, db: Session = Depends(get_db)):
    try:
        return cr.withdraw_report(db, payload.code)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/disputes")
@limiter.limit("3/hour")
def dispute(request: Request, payload: DisputeRequest, db: Session = Depends(get_db)):
    cr.purge_expired(db)
    kind = payload.indicator_type.lower()
    if kind not in {"upi", "bank", "phone", "email", "domain"}:
        raise HTTPException(400, "unsupported indicator type")
    if "@" not in payload.contact_email:
        raise HTTPException(400, "valid contact email required")
    current, _ = cr._pepper_config()
    if not current:
        raise HTTPException(503, "dispute intake is temporarily unavailable")
    version, pepper = current
    normalized = cr.normalize(kind, payload.value)
    digest = cr._digest(kind, normalized, pepper)
    same_domain = (kind == "domain" and
                   payload.contact_email.rsplit("@", 1)[1].casefold().rstrip(".") == normalized)
    raw_token = secrets.token_urlsafe(32) if same_domain else None
    dispute_row = CommunityDispute(indicator_type=kind, digest=digest, key_version=version,
        contact_email=payload.contact_email, reason=payload.reason_code, domain_verified=False,
        verification_token_hash=hashlib.sha256(raw_token.encode()).hexdigest() if raw_token else None,
        verification_expires_at=cr._utcnow() + timedelta(hours=24) if raw_token else None)
    db.add(dispute_row)
    db.commit()
    if raw_token:
        try:
            sent = _send_verification(payload.contact_email, raw_token, normalized)
        except Exception:
            sent = False
        if sent:
            return {"status": "under_review", "message": "A one-time domain verification link was sent."}
    return {"status": "under_review", "message": "Dispute recorded; scoring continues while it is under review."}


@router.get("/disputes/verify")
def verify_dispute(token: str, db: Session = Depends(get_db)):
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    row = db.query(CommunityDispute).filter_by(verification_token_hash=token_hash,
        domain_verified=False).filter(CommunityDispute.verification_expires_at > cr._utcnow()).first()
    if not row:
        raise HTTPException(400, "invalid or expired verification link")
    row.domain_verified = True
    row.verification_token_hash = None
    row.verification_expires_at = None
    db.commit()
    return {"status": "domain_verified", "message": "Domain is suppressed while the dispute is under review."}


@router.get("/indicators/stats")
def indicator_stats(request: Request, db: Session = Depends(get_db)):
    cr.purge_expired(db)
    return cr.stats(db)
