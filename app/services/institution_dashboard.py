"""VIT Pune placement-cell dashboard: category rules and weekly k-anonymous queries.

Single-college simulation. There is exactly one institution, "VIT Pune", created
automatically; every consented community report is attributed to it. Multiple
colleges and a staff login for the dashboard are future scope.
"""
import os
import re
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.models import Institution, InstitutionObservation

INSTITUTION_NAME = "VIT Pune"
BANDS = ("likely legitimate", "insufficient evidence, verify manually", "high risk")
CATEGORIES = (
    "registration_fee", "security_deposit", "training_or_kit_fee", "fake_government_scheme",
    "free_mailbox_impersonation", "lookalike_domain", "sender_spoofing", "no_red_flags", "other",
)


def get_institution(db: Session) -> Institution:
    """Return the single VIT Pune record, creating it on first use."""
    institution = db.query(Institution).order_by(Institution.id).first()
    if institution is None:
        institution = Institution(name=INSTITUTION_NAME)
        db.add(institution)
        db.flush()
    return institution


def record_report_observation(db: Session, report_id: str, band: str, scam_category: str,
                              iso_week: str, is_demo: bool) -> None:
    """Attribute one consented report to VIT Pune (week, band and category only)."""
    if band not in BANDS:
        return
    if scam_category not in CATEGORIES:
        scam_category = "other"
    db.add(InstitutionObservation(institution_id=get_institution(db).id, report_id=report_id,
                                  iso_week=iso_week, band=band, scam_category=scam_category, is_demo=is_demo))


def _include_demo() -> bool:
    return os.getenv("DEMO_MODE") == "1"


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


def last_weeks(today: date | None = None, count: int = 12) -> list[str]:
    today = today or datetime.now(timezone.utc).date()
    weeks = []
    for offset in reversed(range(count)):
        year, week, _ = (today - timedelta(weeks=offset)).isocalendar()
        weeks.append(f"{year}-W{week:02d}")
    return weeks


def dashboard(db: Session, today: date | None = None) -> dict:
    institution = get_institution(db)
    db.commit()
    weeks = last_weeks(today)
    base = [InstitutionObservation.institution_id == institution.id,
            InstitutionObservation.iso_week.in_(weeks)]
    if not _include_demo():
        base.append(InstitutionObservation.is_demo.is_(False))
    rows = db.query(InstitutionObservation.iso_week, InstitutionObservation.band,
        func.count(InstitutionObservation.id)).filter(*base).group_by(
            InstitutionObservation.iso_week, InstitutionObservation.band).all()
    band_counts = {(week, band): count for week, band, count in rows}
    category_rows = db.query(InstitutionObservation.iso_week, InstitutionObservation.scam_category,
        func.count(InstitutionObservation.id)).filter(*base).group_by(
            InstitutionObservation.iso_week, InstitutionObservation.scam_category).all()
    category_counts = {(week, category): count for week, category, count in category_rows}
    return {
        "institution": institution.name,
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
