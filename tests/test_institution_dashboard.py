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
                "task_or_chat_scam", "free_mailbox_impersonation", "lookalike_domain", "sender_spoofing", "no_red_flags",
                "other")) == set(CATEGORIES)


def _test_db():
    from app.db.database import get_db
    from app.main import app
    generator = app.dependency_overrides[get_db]()
    return generator, next(generator)


def test_dashboard_needs_no_key_and_is_vit_pune(api_client):
    response = api_client.get("/trends/dashboard")
    assert response.status_code == 200
    body = response.json()
    assert body["institution"] == "Public"
    assert len(body["weeks"]) == 12
    # The old key-protected endpoint is gone (the SPA catch-all may answer, but with no data).
    assert "by_week_band" not in api_client.get("/institutions/me/dashboard").text


def test_single_institution_is_created_once(api_client):
    from app.models.models import Institution
    api_client.get("/trends/dashboard")
    api_client.get("/trends/dashboard")
    gen, db = _test_db()
    try:
        assert [i.name for i in db.query(Institution).all()] == ["Public"]
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
    body = api_client.get("/trends/dashboard").json()
    assert next(c["count"] for c in body["by_week_band"] if c["week"] == week and c["band"] == band) == "<5"
    assert next(c["count"] for c in body["by_week_category"] if c["week"] == week and c["category"] == category) == "<5"
    db.add(InstitutionObservation(institution_id=institution.id, iso_week=week, band=band, scam_category=category))
    db.commit()
    body = api_client.get("/trends/dashboard").json()
    assert next(c["count"] for c in body["by_week_band"] if c["week"] == week and c["band"] == band) == 5
    assert next(c["count"] for c in body["by_week_category"] if c["week"] == week and c["category"] == category) == 5
    db.query(InstitutionObservation).filter_by(iso_week=week, band=band, scam_category=category).delete()
    db.commit()
    gen.close()


def test_former_college_code_field_is_ignored(api_client):
    # The college-code field no longer exists; an extra form field changes nothing.
    response = api_client.post("/analyze", data={"text": "A small remote internship is open.",
                                                  "institution_code": "ANYTHING"})
    assert response.status_code == 200
    assert "institution" not in response.text.casefold()


def test_add_institution_script_is_gone():
    assert not (ROOT / "scripts" / "add_institution.py").exists()
