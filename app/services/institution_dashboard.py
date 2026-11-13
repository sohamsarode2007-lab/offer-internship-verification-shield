"""Institution trend category rules and weekly k-anonymous dashboard queries."""
import hashlib
import hmac
import re
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.models import Institution, InstitutionObservation

BANDS = ("likely legitimate", "insufficient evidence, verify manually", "high risk")
CATEGORIES = (
    "registration_fee", "security_deposit", "training_or_kit_fee", "fake_government_scheme",
    "free_mailbox_impersonation", "lookalike_domain", "sender_spoofing", "no_red_flags", "other",
)


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def authenticate_api_key(db: Session, api_key: str | None) -> Institution | None:
    if not api_key:
        return None
    digest = hash_api_key(api_key)
    # Hash lookup narrows candidates; compare_digest avoids a normal string comparison.
    institution = db.query(Institution).filter_by(api_key_hash=digest).first()
    if institution and hmac.compare_digest(institution.api_key_hash, digest):
        return institution
    return None


def _check(checks: list[dict], name: str) -> dict:
    return next((c for c in checks if c.get("check_name") == name), {})


def classify_scam(checks: list[dict], text: str) -> str:
    """Assign one non-exclusive trend bucket from existing check findings and text cues."""
    payment = _check(checks, "payment_detection")
    domain = _check(checks, "domain_verification")
    sender = _check(checks, "sender_authentication")
    demands = " ".join(payment.get("demands") or []).casefold()
    content = text.casefold()

    if payment.get("status") == "fail":
        if "security deposit" in demands or "deposit" in demands:
            return "security_deposit"
        if any(term in demands for term in ("training", "kit", "laptop", "onboarding", "document", "background")):
            return "training_or_kit_fee"
        if any(term in demands for term in ("registration", "application", "processing", "joining", "verification")):
            if re.search(r"\b(?:government|govt|ministry|department)\b.{0,50}\bscheme\b|\bscheme\b.{0,50}\b(?:government|govt|ministry)\b", content):
                return "fake_government_scheme"
            return "registration_fee"
        if re.search(r"\b(?:government|govt|ministry|department)\b.{0,50}\bscheme\b|\bscheme\b.{0,50}\b(?:government|govt|ministry)\b", content):
            return "fake_government_scheme"

    domain_details = (domain.get("details") or "").casefold()
    if domain.get("status") == "fail" and "free mailbox" in domain_details:
        return "free_mailbox_impersonation"
    if domain.get("status") == "fail" and any(word in domain_details for word in ("lookalike", "look-alike", "imitates", "brand")):
        return "lookalike_domain"
    if sender.get("status") == "fail" or float(sender.get("risk_points", 0) or 0) > 0:
        return "sender_spoofing"

    failed = any(c.get("status") == "fail" for c in checks)
    scored = any(float(c.get("risk_points", c.get("score", 0)) or 0) > 0 for c in checks)
    if not failed and not scored:
        return "no_red_flags"
    return "other"


def current_iso_week(today: date | None = None) -> str:
    year, week, _ = (today or datetime.now(timezone.utc).date()).isocalendar()
    return f"{year}-W{week:02d}"


def dashboard(db: Session, institution_id: int, today: date | None = None) -> dict:
    today = today or datetime.now(timezone.utc).date()
    weeks = []
    for offset in reversed(range(12)):
        year, week, _ = (today - timedelta(weeks=offset)).isocalendar()
        weeks.append(f"{year}-W{week:02d}")
    rows = db.query(InstitutionObservation.iso_week, InstitutionObservation.band,
        func.count(InstitutionObservation.id)).filter(
            InstitutionObservation.institution_id == institution_id,
            InstitutionObservation.iso_week.in_(weeks)
        ).group_by(InstitutionObservation.iso_week, InstitutionObservation.band).all()
    band_counts = {(week, band): count for week, band, count in rows}
    category_rows = db.query(InstitutionObservation.iso_week, InstitutionObservation.scam_category,
        func.count(InstitutionObservation.id)).filter(
            InstitutionObservation.institution_id == institution_id,
            InstitutionObservation.iso_week.in_(weeks)
        ).group_by(InstitutionObservation.iso_week, InstitutionObservation.scam_category).all()
    category_counts = {(week, category): count for week, category, count in category_rows}
    return {
        "weeks": weeks,
        "by_week_band": [{"week": week, "band": band,
                          "count": (n if n >= 5 else "<5")}
                         for week in weeks for band in BANDS
                         for n in [band_counts.get((week, band), 0)]],
        "by_week_category": [{"week": week, "category": category,
                              "count": (n if n >= 5 else "<5")}
                             for week in weeks for category in CATEGORIES
                             for n in [category_counts.get((week, category), 0)]],
    }
