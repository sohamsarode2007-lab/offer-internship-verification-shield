import hashlib
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from app.services.institution_dashboard import CATEGORIES, classify_scam


ROOT = Path(__file__).resolve().parents[1]


def test_scam_categories_follow_rule_priority():
    def classify(demands=(), domain=None, sender=None, text=""):
        checks = [
            {"check_name": "payment_detection", "status": "fail" if demands else "pass", "demands": list(demands)},
            {"check_name": "domain_verification", **(domain or {"status": "pass", "details": ""})},
            {"check_name": "sender_authentication", **(sender or {"status": "not_applicable", "risk_points": 0})},
        ]
        return classify_scam(checks, text)

    assert classify(["registration fee"]) == "registration_fee"
    assert classify(["refundable security deposit"]) == "security_deposit"
    assert classify(["training kit fee"]) == "training_or_kit_fee"
    assert classify(["processing fee"], text="Government scheme verification benefit") == "fake_government_scheme"
    assert classify(domain={"status": "fail", "details": "Contact address uses the free mailbox provider."}) == "free_mailbox_impersonation"
    assert classify(domain={"status": "fail", "details": "Lookalike domain resembles a protected brand."}) == "lookalike_domain"
    assert classify(sender={"status": "fail", "risk_points": 30}) == "sender_spoofing"
    assert classify() == "no_red_flags"
    assert classify(domain={"status": "fail", "details": "No MX records found."}) == "other"
    assert set(("registration_fee", "security_deposit", "training_or_kit_fee", "fake_government_scheme",
                "free_mailbox_impersonation", "lookalike_domain", "sender_spoofing", "no_red_flags", "other")) == set(CATEGORIES)


def _test_db(api_client):
    from app.db.database import get_db
    from app.main import app
    generator = app.dependency_overrides[get_db]()
    return generator, next(generator)


def test_dashboard_requires_api_key(api_client):
    assert api_client.get("/institutions/me/dashboard").status_code == 401
    assert api_client.get("/institutions/me/dashboard", headers={"X-API-Key": "wrong"}).status_code == 401


def test_dashboard_suppresses_cells_below_five(api_client):
    from app.models.models import Institution, InstitutionObservation
    from app.services.institution_dashboard import current_iso_week, hash_api_key
    gen, db = _test_db(api_client)
    key = "test-dashboard-" + uuid.uuid4().hex
    code = "D" + uuid.uuid4().hex[:12].upper()
    institution = Institution(name="Synthetic College", code=code, api_key_hash=hash_api_key(key))
    db.add(institution)
    db.flush()
    for _ in range(4):
        db.add(InstitutionObservation(institution_id=institution.id, iso_week=current_iso_week(),
            band="high risk", scam_category="registration_fee"))
    db.commit()
    response = api_client.get("/institutions/me/dashboard", headers={"X-API-Key": key})
    assert response.status_code == 200
    body = response.json()
    assert len(body["weeks"]) == 12
    week = current_iso_week()
    assert next(c["count"] for c in body["by_week_band"] if c["week"] == week and c["band"] == "high risk") == "<5"
    assert next(c["count"] for c in body["by_week_category"] if c["week"] == week and c["category"] == "registration_fee") == "<5"
    db.add(InstitutionObservation(institution_id=institution.id, iso_week=week, band="high risk", scam_category="registration_fee"))
    db.commit()
    body = api_client.get("/institutions/me/dashboard", headers={"X-API-Key": key}).json()
    assert next(c["count"] for c in body["by_week_band"] if c["week"] == week and c["band"] == "high risk") == 5
    assert next(c["count"] for c in body["by_week_category"] if c["week"] == week and c["category"] == "registration_fee") == 5
    gen.close()


def test_analyze_stores_only_weekly_institution_aggregate(api_client):
    from app.models.models import Institution, InstitutionObservation, Offer
    from app.services.institution_dashboard import hash_api_key
    gen, db = _test_db(api_client)
    key = "test-api-" + uuid.uuid4().hex
    code = "A" + uuid.uuid4().hex[:12].upper()
    institution = Institution(name="Synthetic College", code=code, api_key_hash=hash_api_key(key))
    db.add(institution)
    db.commit()
    text = ("Selected for a software role. Contact HR at hiring@company.example. "
            "Pay registration fee Rs 500 to recruit@ybl.")
    response = api_client.post("/analyze", data={"text": text, "institution_code": code.lower()})
    assert response.status_code == 200, response.text
    observation = db.query(InstitutionObservation).filter_by(institution_id=institution.id).one()
    assert re.fullmatch(r"\d{4}-W\d{2}", observation.iso_week)
    assert observation.band == response.json()["risk_band"]
    assert observation.scam_category == "registration_fee"
    assert {c.name for c in InstitutionObservation.__table__.columns} == {
        "id", "institution_id", "iso_week", "band", "scam_category"}
    assert all(offer.raw_text is None and offer.company_name is None for offer in db.query(Offer).all())
    gen.close()


def test_unknown_institution_code_is_silently_ignored(api_client):
    from app.models.models import InstitutionObservation
    gen, db = _test_db(api_client)
    before = db.query(InstitutionObservation).count()
    gen.close()
    response = api_client.post("/analyze", data={"text": "A small remote internship is open.",
        "institution_code": "DOES-NOT-EXIST"})
    assert response.status_code == 200
    assert "institution" not in response.text.casefold()
    gen, db = _test_db(api_client)
    assert db.query(InstitutionObservation).count() == before
    gen.close()


def test_cli_creates_and_shows_api_key_once(tmp_path):
    db_path = tmp_path / "institutions.sqlite3"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    command = [sys.executable, str(ROOT / "scripts" / "add_institution.py"),
        "--name", "Synthetic College", "--code", "SYNTH"]
    first = subprocess.run(command, env=env, capture_output=True, text=True, check=True)
    key = first.stdout.strip().splitlines()[-1]
    assert len(key) > 30
    assert "API key (shown once" in first.stdout
    duplicate = subprocess.run(command, env=env, capture_output=True, text=True)
    assert duplicate.returncode != 0
    assert key not in duplicate.stdout
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.models.models import Institution
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    with Session(engine) as db:
        stored = db.query(Institution).one().api_key_hash
    assert stored == hashlib.sha256(key.encode()).hexdigest()
    assert stored != key
    engine.dispose()
