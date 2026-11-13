"""Seed synthetic community reports through the same consent/token service flow.

Requires DEMO_MODE=1 and an operator-provided INDICATOR_PEPPER. The committed
fixture contains only synthetic .example domains and a fictional UPI handle.
"""
import csv
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    if os.getenv("DEMO_MODE") != "1":
        raise SystemExit("Set DEMO_MODE=1 to seed demo-only community reports.")
    if not os.getenv("INDICATOR_PEPPER"):
        raise SystemExit("Set INDICATOR_PEPPER in the environment; no default pepper is used.")

    from app.db.database import SessionLocal, init_dev_db
    from app.models.models import CommunityReport
    from app.services import community_reports
    from app.services.fact_extraction import extract_facts
    from app.services.payment_detection import detect_payment_demand

    init_dev_db()
    db = SessionLocal()
    added = 0
    try:
        with (ROOT / "fixtures" / "demo" / "scam_reports.csv").open(encoding="utf-8", newline="") as source:
            rows = list(csv.DictReader(source))
        for row in rows:
            text = row["text"]
            facts = extract_facts(text)
            indicators = community_reports.extract_indicators(text, None, detect_payment_demand(facts))
            signature = community_reports.minhash_signature(text)
            signature_json = json.dumps(signature)
            if db.query(CommunityReport).filter_by(signature=signature_json, is_demo=True).first():
                continue
            token, _ = community_reports.issue_report_token(db, indicators, signature)
            selected = [x["indicator_type"] + ":" + x["digest"] for x in indicators]
            community_reports.accept_report(db, token, selected, True, community_reports.CONSENT_VERSION)
            added += 1
    finally:
        db.close()
    print(f"Added {added} synthetic demo report(s).")


if __name__ == "__main__":
    main()
