"""Seed the simulated reports (fictional senders) and simulated checks (DEMO_MODE=1 only).

Requires DEMO_MODE=1 and an operator-provided INDICATOR_PEPPER. Idempotent: running it
again adds nothing. See app/services/demo_seed.py and fixtures/demo/simulated_senders.csv.
"""
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
    from app.services.demo_seed import seed_vit_checks, seed_vit_simulation

    init_dev_db()
    db = SessionLocal()
    try:
        added = seed_vit_simulation(db)
        checks = seed_vit_checks(db)
    finally:
        db.close()
    print(f"Added {added} simulated report(s) and {checks} simulated check(s).")


if __name__ == "__main__":
    main()
