import os
import re
import uuid
from pathlib import Path

from app.services.institution_dashboard import CATEGORIES, classify_scam


ROOT = Path(__file__).resolve().parents[1]
PAYMENT_TEXT = ("Selected for a software role. Contact HR at hiring@company.example. "
                "Pay registration fee Rs 500 to recruit@ybl.")


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


def _test_db():
    from app.db.database import get_db
    from app.main import app
    generator = app.dependency_overrides[get_db]()
    return generator, next(generator)


def test_dashboard_needs_no_key_and_is_vit_pune(api_client):
    response = api_client.get("/placement-cell/dashboard")
    assert response.status_code == 200
    body = response.json()
    assert body["institution"] == "VIT Pune"
    assert len(body["weeks"]) == 12
    # The old key-protected endpoint is gone (the SPA catch-all may answer, but with no data).
    assert "by_week_band" not in api_client.get("/institutions/me/dashboard").text


def test_single_institution_is_created_once(api_client):
    from app.models.models import Institution
    api_client.get("/placement-cell/dashboard")
    api_client.get("/placement-cell/dashboard")
    gen, db = _test_db()
    try:
        assert [i.name for i in db.query(Institution).all()] == ["VIT Pune"]
        assert {c.name for c in Institution.__table__.columns} == {"id", "name"}
    finally:
        gen.close()


def test_dashboard_suppresses_cells_below_five(api_client):
    from app.models.models import InstitutionObservation
    from app.services.institution_dashboard import get_institution, last_weeks
    gen, db = _test_db()
    institution = get_institution(db)
    # A week/band/category no other test writes to, so the test also holds on a shared Postgres DB.
    week, band, category = last_weeks()[0], "likely legitimate", "sender_spoofing"
    existing = db.query(InstitutionObservation).filter_by(iso_week=week, band=band, scam_category=category,
                                                          is_demo=False).count()
    assert existing <= 4
    for _ in range(4 - existing):
        db.add(InstitutionObservation(institution_id=institution.id, iso_week=week, band=band, scam_category=category))
    db.commit()
    body = api_client.get("/placement-cell/dashboard").json()
    assert next(c["count"] for c in body["by_week_band"] if c["week"] == week and c["band"] == band) == "<5"
    assert next(c["count"] for c in body["by_week_category"] if c["week"] == week and c["category"] == category) == "<5"
    db.add(InstitutionObservation(institution_id=institution.id, iso_week=week, band=band, scam_category=category))
    db.commit()
    body = api_client.get("/placement-cell/dashboard").json()
    assert next(c["count"] for c in body["by_week_band"] if c["week"] == week and c["band"] == band) == 5
    assert next(c["count"] for c in body["by_week_category"] if c["week"] == week and c["category"] == category) == 5
    db.query(InstitutionObservation).filter_by(iso_week=week, band=band, scam_category=category).delete()
    db.commit()
    gen.close()


def test_analyze_without_consent_records_no_observation(api_client, monkeypatch):
    from app.models.models import InstitutionObservation, Offer
    monkeypatch.setenv("INDICATOR_PEPPER", "test-pepper-" + uuid.uuid4().hex)
    gen, db = _test_db()
    before = db.query(InstitutionObservation).count()
    gen.close()
    response = api_client.post("/analyze", data={"text": PAYMENT_TEXT})
    assert response.status_code == 200, response.text
    assert response.json()["report_token"]
    gen, db = _test_db()
    try:
        assert db.query(InstitutionObservation).count() == before
        assert all(offer.raw_text is None and offer.company_name is None for offer in db.query(Offer).all())
    finally:
        gen.close()


def test_former_college_code_field_is_ignored(api_client):
    # The college-code field no longer exists; an extra form field changes nothing.
    response = api_client.post("/analyze", data={"text": "A small remote internship is open.",
                                                  "institution_code": "ANYTHING"})
    assert response.status_code == 200
    assert "institution" not in response.text.casefold()


def test_consented_report_counts_for_vit_pune_and_withdrawal_removes_it(api_client, monkeypatch):
    from app.models.models import InstitutionObservation
    monkeypatch.setenv("INDICATOR_PEPPER", "test-pepper-" + uuid.uuid4().hex)
    gen, db = _test_db()
    before = db.query(InstitutionObservation).count()
    gen.close()
    analysis = api_client.post("/analyze", data={"text": PAYMENT_TEXT}).json()
    selected = [i["id"] for i in analysis["reportable_indicators"]]
    from app.services.community_reports import CONSENT_VERSION
    reported = api_client.post("/report", json={"report_token": analysis["report_token"], "consent": True,
        "consent_version": CONSENT_VERSION, "selected_indicators": selected})
    assert reported.status_code == 200, reported.text
    gen, db = _test_db()
    try:
        assert db.query(InstitutionObservation).count() == before + 1
        observation = db.query(InstitutionObservation).order_by(InstitutionObservation.id.desc()).first()
        assert observation.institution.name == "VIT Pune"
        assert re.fullmatch(r"\d{4}-W\d{2}", observation.iso_week)
        assert observation.band == analysis["risk_band"]
        assert observation.scam_category == "registration_fee"
        assert {c.name for c in InstitutionObservation.__table__.columns} == {
            "id", "institution_id", "report_id", "iso_week", "band", "scam_category", "is_demo"}
    finally:
        gen.close()
    assert api_client.post("/report/withdraw", json={"code": reported.json()["withdrawal_code"]}).status_code == 200
    gen, db = _test_db()
    try:
        assert db.query(InstitutionObservation).count() == before
    finally:
        gen.close()


def test_add_institution_script_is_gone():
    assert not (ROOT / "scripts" / "add_institution.py").exists()
