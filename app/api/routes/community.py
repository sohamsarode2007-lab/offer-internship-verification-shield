"""Consent, withdrawal, disputes, and aggregate community indicator endpoints."""
import hashlib
import os
import secrets
import smtplib
import ssl
from datetime import timedelta
from email.message import EmailMessage

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func
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


class VerifyRequest(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class DisputeRequest(BaseModel):
    indicator_type: str
    value: str = Field(min_length=3, max_length=320)
    contact_email: str = Field(min_length=5, max_length=320)
    # A fixed code, never free text.
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
    message.set_content(f"Verify this domain dispute for {domain}: {base_url.rstrip('/')}/verify-dispute#token={token}\nThis link expires in 24 hours.")
    with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=10) as smtp:
        # create_default_context() verifies the server certificate and host name; smtplib's own default does not.
        smtp.starttls(context=ssl.create_default_context())
        username = os.getenv("SMTP_USERNAME")
        if username:
            smtp.login(username, os.getenv("SMTP_PASSWORD", ""))
        smtp.send_message(message)
    return True


@router.post("/report")
@limiter.limit("5/hour")
def report(request: Request, payload: ReportRequest, db: Session = Depends(get_db)):
    cr.purge_if_due(db)
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
    cr.purge_if_due(db)
    kind = payload.indicator_type.lower()
    if kind not in {"upi", "bank", "phone", "email", "domain"}:
        raise HTTPException(400, "unsupported indicator type")
    if "@" not in payload.contact_email:
        raise HTTPException(400, "valid contact email required")
    current, _ = cr._pepper_config()
    if not current:
        raise HTTPException(503, "dispute intake is temporarily unavailable")
    version, pepper = current
    try:
        normalized = cr.normalize(kind, payload.value)
    except ValueError:
        raise HTTPException(400, "value does not match the indicator type (a bank value looks like account|IFSC)")
    digest = cr._digest(kind, normalized, pepper)
    # Caps on open disputes: one address or one indicator cannot hold the review queue or hide a warning indefinitely.
    open_rows = db.query(CommunityDispute).filter(CommunityDispute.resolved_at.is_(None),
        CommunityDispute.created_at > cr.active_dispute_cutoff())
    email_key = payload.contact_email.strip().casefold()
    if open_rows.filter(func.lower(CommunityDispute.contact_email) == email_key).count() >= cr.MAX_ACTIVE_DISPUTES_PER_EMAIL:
        raise HTTPException(429, "this address already has the maximum number of open disputes")
    if open_rows.filter_by(indicator_type=kind, digest=digest).count() >= cr.MAX_ACTIVE_DISPUTES_PER_INDICATOR:
        raise HTTPException(429, "this indicator already has the maximum number of open disputes")
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


@router.post("/disputes/verify")
@limiter.limit("10/hour")
def verify_dispute(request: Request, payload: VerifyRequest, db: Session = Depends(get_db)):
    """POST with the code in the body: a code in a URL would end up in access logs and browser history."""
    token_hash = hashlib.sha256(payload.token.encode()).hexdigest()
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
@limiter.limit("30/minute")
def indicator_stats(request: Request, db: Session = Depends(get_db)):
    cr.purge_if_due(db)
    return cr.stats(db)
