"""Public scam-trends dashboard: category rules and weekly k-anonymous queries.

One aggregate record, "Public", created
automatically. Every /analyze call adds one anonymous trend row (ISO week, band,
scam category; see docs/PRIVACY_DESIGN.md). The senders table comes from consented
community reports. Multiple colleges and a staff login are future scope.
"""
import os
import re
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.models import Institution, InstitutionObservation

INSTITUTION_NAME = "Public"
BANDS = ("likely legitimate", "insufficient evidence, verify manually", "high risk")
CATEGORIES = (
    "registration_fee", "security_deposit", "training_or_kit_fee", "fake_government_scheme",
    "task_or_chat_scam", "free_mailbox_impersonation", "lookalike_domain", "sender_spoofing", "no_red_flags", "other",
)


def get_institution(db: Session) -> Institution:
    """Return the single public record, creating it on first use."""
    institution = db.query(Institution).order_by(Institution.id).first()
    if institution is None:
        institution = Institution(name=INSTITUTION_NAME)
        db.add(institution)
        db.flush()
    return institution


def record_check_observation(db: Session, band: str, scam_category: str, iso_week: str,
                             is_demo: bool, report_id: str | None = None, is_simulated: bool = False) -> None:
    """One anonymous public trend row: ISO week, band and category only.

    Every /analyze call records one (report_id stays NULL: not linked to anything).
    report_id is set only for the simulated demo reports in app/services/demo_seed.py.
    """
    if band not in BANDS:
        return
    if scam_category not in CATEGORIES:
        scam_category = "other"
    db.add(InstitutionObservation(institution_id=get_institution(db).id, report_id=report_id,
                                  iso_week=iso_week, band=band, scam_category=scam_category, is_demo=is_demo,
                                  is_simulated=is_simulated))


TREND_RETENTION_WEEKS = 104  # 24 months


def purge_old_observations(db: Session, today: date | None = None) -> int:
    """Delete trend rows older than 24 months (by ISO week; 'YYYY-Www' sorts correctly)."""
    cutoff = last_weeks(today, TREND_RETENTION_WEEKS + 1)[0]
    return db.query(InstitutionObservation).filter(InstitutionObservation.iso_week < cutoff).delete(
        synchronize_session=False)


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

    if _check(checks, "scam_text_patterns").get("status") == "fail":
        return "task_or_chat_scam"

    domain_details = (domain.get("details") or "").casefold()
    if domain.get("status") == "fail" and ("free mailbox" in domain_details or "disposable" in domain_details):
        return "free_mailbox_impersonation"
    if domain.get("status") == "fail" and any(word in domain_details for word in ("lookalike", "look-alike", "imitates", "brand", "official recruitment domain")):
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


SENDER_THRESHOLD = 3
DISPUTED_STATUS = "disputed by the company, under review"
SENDER_CSV_COLUMNS = ("indicator", "type", "reports", "first_week", "last_week", "most_common_category",
                      "dispute_status")


def top_senders(db: Session) -> list[dict]:
    """Senders (masked indicators) reported by 3+ distinct consented v3 reports, by count.

    Only masked display forms leave this function; digests are used for grouping and
    dispute lookup only. Withdrawn reports never count; demo reports count only in DEMO_MODE.
    """
    from collections import Counter
    from app.models.models import CommunityDispute, CommunityIndicator, CommunityReport
    from app.services.community_reports import CONSENT_VERSION

    query = db.query(CommunityIndicator.indicator_type, CommunityIndicator.digest, CommunityIndicator.key_version,
                     CommunityIndicator.report_id, CommunityIndicator.masked_display,
                     CommunityIndicator.iso_week, CommunityIndicator.scam_category).join(CommunityReport).filter(
        CommunityReport.withdrawn.is_(False),
        CommunityReport.consent_version >= CONSENT_VERSION,
        CommunityIndicator.masked_display.isnot(None),
    )
    if not _include_demo():
        query = query.filter(CommunityReport.is_demo.is_(False))

    groups: dict[tuple, dict] = {}
    for kind, digest, version, report_id, display, week, category in query.all():
        group = groups.setdefault((kind, digest, version), {
            "indicator_type": kind, "indicator": display, "reports": set(), "weeks": [], "categories": Counter()})
        group["reports"].add(report_id)
        if week:
            group["weeks"].append(week)
        if category:
            group["categories"][category] += 1

    disputed = {(d.indicator_type, d.digest, d.key_version)
                for d in db.query(CommunityDispute).filter(CommunityDispute.resolved_at.is_(None)).all()}
    senders = []
    for key, group in groups.items():
        count = len(group["reports"])
        if count < SENDER_THRESHOLD:
            continue
        category = (sorted(group["categories"].items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
                    if group["categories"] else "other")
        senders.append({
            "indicator": group["indicator"],
            "indicator_type": group["indicator_type"],
            "reports": count,
            "first_week": min(group["weeks"]) if group["weeks"] else None,
            "last_week": max(group["weeks"]) if group["weeks"] else None,
            "most_common_category": category,
            "dispute_status": DISPUTED_STATUS if key in disputed else None,
        })
    senders.sort(key=lambda s: (-s["reports"], s["indicator_type"], s["indicator"]))
    return senders


def _csv_safe(value) -> str:
    """Prevent spreadsheet formula injection (cells starting with = + - @)."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


def senders_csv(db: Session) -> str:
    import csv
    import io
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(SENDER_CSV_COLUMNS)
    for s in top_senders(db):
        writer.writerow([_csv_safe(s["indicator"]), s["indicator_type"], s["reports"], s["first_week"] or "",
                         s["last_week"] or "", s["most_common_category"], s["dispute_status"] or "not disputed"])
    return out.getvalue()


SUPPRESSION_THRESHOLD = 5
TREND_RATIO = 1.25  # weekly rate change needed to call a trend Rising or Falling


def _shown(n: int):
    return n if n >= SUPPRESSION_THRESHOLD else "<5"


def trend_word(last_4: int, previous_8: int) -> str:
    """Compare weekly rates: last 4 weeks vs the 8 weeks before them."""
    recent, earlier = last_4 / 4, previous_8 / 8
    if earlier == 0:
        return "Rising" if recent > 0 else "Steady"
    if recent >= earlier * TREND_RATIO:
        return "Rising"
    if recent <= earlier / TREND_RATIO:
        return "Falling"
    return "Steady"


def category_summary(weeks: list[str], category_counts: dict) -> list[dict]:
    """One row per category: 12-week total, last 4 weeks, previous 8 weeks and a trend word.

    Every count below five is shown as "<5". A category whose 12-week total is below
    five gets no trend word (None) and sorts after the visible ones, alphabetically,
    so neither reveals the suppressed numbers.
    """
    rows = []
    for category in CATEGORIES:
        per_week = [category_counts.get((week, category), 0) for week in weeks]
        last_4, previous_8 = sum(per_week[-4:]), sum(per_week[:-4])
        total = last_4 + previous_8
        rows.append({"category": category, "total": _shown(total), "last_4_weeks": _shown(last_4),
                     "previous_8_weeks": _shown(previous_8),
                     "trend": trend_word(last_4, previous_8) if total >= SUPPRESSION_THRESHOLD else None,
                     "_sort": total if total >= SUPPRESSION_THRESHOLD else -1})
    rows.sort(key=lambda r: (-r["_sort"], r["category"]))
    for r in rows:
        del r["_sort"]
    return rows


def _weekly_counts(db: Session, institution: Institution, weeks: list[str]):
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
    return band_counts, category_counts


def dashboard(db: Session, today: date | None = None) -> dict:
    institution = get_institution(db)
    db.commit()
    weeks = last_weeks(today)
    band_counts, category_counts = _weekly_counts(db, institution, weeks)
    return {
        "institution": institution.name,
        "sender_threshold": SENDER_THRESHOLD,
        "top_senders": top_senders(db),
        "weeks": weeks,
        "by_week_band": [{"week": week, "band": band, "count": _shown(band_counts.get((week, band), 0))}
                         for week in weeks for band in BANDS],
        # Full weekly category data stays in the API and in GET /trends/weekly.csv.
        "by_week_category": [{"week": week, "category": category,
                              "count": _shown(category_counts.get((week, category), 0))}
                             for week in weeks for category in CATEGORIES],
        "category_summary": category_summary(weeks, category_counts),
    }


WEEKLY_CSV_COLUMNS = ("week", "breakdown", "value", "count")


def weekly_csv(db: Session, today: date | None = None) -> str:
    """Full 12-week data: one row per week x band and week x category, with '<5' applied."""
    import csv
    import io
    institution = get_institution(db)
    db.commit()
    weeks = last_weeks(today)
    band_counts, category_counts = _weekly_counts(db, institution, weeks)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(WEEKLY_CSV_COLUMNS)
    for week in weeks:
        for band in BANDS:
            writer.writerow([week, "band", band, _shown(band_counts.get((week, band), 0))])
        for category in CATEGORIES:
            writer.writerow([week, "category", category, _shown(category_counts.get((week, category), 0))])
    return out.getvalue()
