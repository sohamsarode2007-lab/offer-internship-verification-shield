"""Simulated VIT Pune community reports for the demo (DEMO_MODE=1 only).

Reads fixtures/demo/vit_simulated_senders.csv: 8 FICTIONAL senders (.example domains and
made-up local parts, plus one made-up gmail.com address, two UPI IDs and one phone
number). Each simulated report is a consented-report row exactly like a real one
(HMAC digest, masked display form, ISO week, scam category, VIT Pune observation),
flagged is_demo so it counts only in DEMO_MODE. Raw values are hashed and masked in
memory; they are never stored.

Reports are spread over the last 12 ISO weeks in campaign-like waves. Report IDs are
deterministic, so seeding is idempotent: running it again adds nothing.
"""
import csv
import hashlib
import json
import os
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.models import CommunityDispute, CommunityIndicator, CommunityReport, CommunityTemplateBand
from app.services import community_reports as cr
from app.services.institution_dashboard import record_report_observation

SENDERS_CSV = Path(__file__).resolve().parents[2] / "fixtures" / "demo" / "vit_simulated_senders.csv"
SEED_NAMESPACE = uuid.UUID("6f1d2b4e-9a57-4c1e-8f0b-5a3e2d7c9b10")
# Reports per ISO week, oldest first (12 weeks; total must equal the CSV report total).
# Scam campaigns arrive in waves, so a few weeks are busy. The dashboard still
# suppresses any cell below five; only the busy weeks show bars.
WEEKLY_REPORTS = (1, 0, 2, 6, 1, 2, 7, 1, 2, 8, 6, 9)
BAND_HIGH, BAND_MANUAL = "high risk", "insufficient evidence, verify manually"


def load_senders() -> list[dict]:
    with SENDERS_CSV.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    for row in rows:
        row["reports"] = int(row["reports"])
        row["high_risk_reports"] = int(row["high_risk_reports"])
        row["disputed"] = row["disputed"].strip().lower() == "true"
    return rows


def _week_start(today: date, weeks_ago: int) -> date:
    monday = today - timedelta(days=today.weekday())
    return monday - timedelta(weeks=weeks_ago)


def _schedule(senders: list[dict]) -> list[tuple[dict, int, int]]:
    """Assign every report a weeks-ago offset: round-robin across senders so each spreads out."""
    queue = []
    remaining = {s["key"]: s["reports"] for s in senders}
    while any(remaining.values()):
        for sender in senders:
            if remaining[sender["key"]]:
                index = sender["reports"] - remaining[sender["key"]]
                queue.append((sender, index))
                remaining[sender["key"]] -= 1
    slots = [weeks_ago for weeks_ago, n in zip(range(len(WEEKLY_REPORTS) - 1, -1, -1), WEEKLY_REPORTS)
             for _ in range(n)]
    if len(slots) != len(queue):
        raise ValueError(f"WEEKLY_REPORTS totals {len(slots)} but the CSV lists {len(queue)} reports")
    return [(sender, index, weeks_ago) for (sender, index), weeks_ago in zip(queue, slots)]


def seed_vit_simulation(db: Session, today: date | None = None) -> int:
    """Insert the simulated reports that are missing. Returns how many reports were added."""
    if os.getenv("DEMO_MODE") != "1":
        raise RuntimeError("Simulated VIT reports can only be seeded with DEMO_MODE=1.")
    current, _ = cr._pepper_config()
    if not current:
        raise RuntimeError("Set INDICATOR_PEPPER; no default pepper is used.")
    version, pepper = current
    today = today or datetime.now(timezone.utc).date()
    senders = load_senders()
    added = 0
    for sender, index, weeks_ago in _schedule(senders):
        report_id = str(uuid.uuid5(SEED_NAMESPACE, f"{sender['key']}:{index}"))
        if db.get(CommunityReport, report_id):
            continue
        day = _week_start(today, weeks_ago) + timedelta(days=index % 5)
        when = datetime.combine(min(day, today), time(10, 0), tzinfo=timezone.utc)
        year, week, _ = when.date().isocalendar()
        iso_week = f"{year}-W{week:02d}"
        # A sender's first reports were less clear-cut; the later (busier) ones demanded money.
        band = BAND_MANUAL if index < sender["reports"] - sender["high_risk_reports"] else BAND_HIGH
        kind, value = sender["indicator_type"], sender["value"]
        signature = cr.minhash_signature(f"{sender['template']} Reference {index + 1}.")
        report = CommunityReport(
            id=report_id, consent_version=cr.CONSENT_VERSION, signature=json.dumps(signature),
            created_at=when, last_seen_at=datetime.now(timezone.utc),
            withdrawal_code_hash=hashlib.sha256(f"demo-seed:{report_id}".encode()).hexdigest(), is_demo=True)
        db.add(report)
        db.add(CommunityIndicator(
            report_id=report_id, indicator_type=kind, digest=cr._digest(kind, value, pepper), key_version=version,
            created_at=when, last_seen_at=when, masked_display=cr.masked(kind, value),
            iso_week=iso_week, scam_category=sender["category"]))
        for template_band, bucket in cr._signature_bands(signature):
            db.add(CommunityTemplateBand(report_id=report_id, band=template_band, bucket=bucket))
        db.flush()
        record_report_observation(db, report_id, band, sender["category"], iso_week, is_demo=True)
        added += 1

    for sender in senders:
        if not sender["disputed"]:
            continue
        digest = cr._digest(sender["indicator_type"], sender["value"], pepper)
        exists = db.query(CommunityDispute).filter_by(indicator_type=sender["indicator_type"], digest=digest,
                                                      key_version=version, resolved_at=None).first()
        if not exists:
            db.add(CommunityDispute(
                indicator_type=sender["indicator_type"], digest=digest, key_version=version,
                contact_email=f"legal@{sender['value']}" if sender["indicator_type"] == "domain" else "legal@company.example",
                reason="Simulated demo dispute: the company says this sender is theirs."))
    db.commit()
    return added
