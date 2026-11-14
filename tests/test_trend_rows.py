"""Every /analyze call records one anonymous VIT Pune trend row (ISO week, band, category only)."""
import re
import uuid
from datetime import date, timedelta

PAYMENT_TEXT = ("Acme Placement Desk\nSelected for a software role. Contact HR at hiring@company.example "
                "or call +91 9123456789. Pay registration fee Rs 500 to recruit@ybl.")
OFFER_FRAGMENTS = ["Acme", "Placement Desk", "hiring@company.example", "company.example", "9123456789",
                   "recruit@ybl", "Rs 500", "software role"]


def _db():
    from app.db.database import get_db
    from app.main import app
    gen = app.dependency_overrides[get_db]()
    return gen, next(gen)


def _rows(db):
    from app.models.models import InstitutionObservation
    return db.query(InstitutionObservation)


def test_real_check_adds_exactly_one_anonymous_row(api_client, monkeypatch):
    from app.models.models import InstitutionObservation, Offer
    monkeypatch.delenv("DEMO_MODE", raising=False)
    gen, db = _db()
    before_ids = {r.id for r in _rows(db)}
    gen.close()

    response = api_client.post("/analyze", data={"text": PAYMENT_TEXT},
                               files={"file": ("Priya_Sharma_offer.txt", b"Joining letter for Priya Sharma.")})
    assert response.status_code == 200, response.text

    gen, db = _db()
    try:
        new = [r for r in _rows(db) if r.id not in before_ids]
        assert len(new) == 1
        row = new[0]
        assert re.fullmatch(r"\d{4}-W\d{2}", row.iso_week)
        assert row.band == response.json()["risk_band"]
        assert row.scam_category == "registration_fee"
        assert row.report_id is None and row.is_demo is False
        assert row.institution.name == "VIT Pune"
        # The table has only these fields: no text, identifiers, file name, IP or timestamps.
        assert {c.name for c in InstitutionObservation.__table__.columns} == {
            "id", "institution_id", "report_id", "iso_week", "band", "scam_category", "is_demo", "is_simulated"}
        assert row.is_simulated is False
        stored = " ".join(str(getattr(row, c.name)) for c in InstitutionObservation.__table__.columns)
        for fragment in OFFER_FRAGMENTS + ["Priya", "Sharma", "testclient", "127.0.0.1"]:
            assert fragment not in stored
        # And the analysis record itself still stores no offer text, file name or company name.
        assert all(o.raw_text is None and o.file_path is None and o.company_name is None for o in db.query(Offer))
    finally:
        gen.close()


def test_report_adds_no_second_row_and_withdrawal_keeps_the_anonymous_row(api_client, monkeypatch):
    from app.services.community_reports import CONSENT_VERSION
    monkeypatch.setenv("INDICATOR_PEPPER", "trend-test-" + uuid.uuid4().hex)
    gen, db = _db()
    before = _rows(db).count()
    gen.close()
    analysis = api_client.post("/analyze", data={"text": PAYMENT_TEXT}).json()
    reported = api_client.post("/report", json={"report_token": analysis["report_token"], "consent": True,
        "consent_version": CONSENT_VERSION, "selected_indicators": [i["id"] for i in analysis["reportable_indicators"]]})
    assert reported.status_code == 200, reported.text
    gen, db = _db()
    assert _rows(db).count() == before + 1            # one row for the check, none for the report
    gen.close()
    assert api_client.post("/report/withdraw", json={"code": reported.json()["withdrawal_code"]}).status_code == 200
    gen, db = _db()
    assert _rows(db).count() == before + 1            # unlinked, so withdrawal cannot remove it
    gen.close()


def test_rejected_requests_add_no_row(api_client):
    gen, db = _db()
    before = _rows(db).count()
    gen.close()
    assert api_client.post("/analyze", data={}).status_code == 400
    assert api_client.post("/analyze", files={"file": ("x.exe", b"MZ")}).status_code == 415
    assert api_client.post("/analyze", files={"file": ("x.png", b"not an image")}).status_code == 422
    gen, db = _db()
    assert _rows(db).count() == before
    gen.close()


def test_checks_in_demo_mode_are_demo_flagged(api_client, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    gen, db = _db()
    before_ids = {r.id for r in _rows(db)}
    gen.close()
    api_client.post("/analyze", data={"text": "A remote internship offer with no details."})
    gen, db = _db()
    new = [r for r in _rows(db) if r.id not in before_ids]
    assert len(new) == 1 and new[0].is_demo is True and new[0].is_simulated is False
    gen.close()


def test_demo_mode_check_before_seeding_does_not_block_the_check_seeder(api_client, monkeypatch, tmp_path):
    # Regression: real demo-mode rows must not be mistaken for already-seeded simulated checks.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.database import Base
    from app.models.models import InstitutionObservation
    from app.services import demo_seed, institution_dashboard
    monkeypatch.setenv("DEMO_MODE", "1")
    engine = create_engine(f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        institution_dashboard.record_check_observation(db, "high risk", "other", "2026-W46", is_demo=True)
        db.commit()
        added = demo_seed.seed_vit_checks(db)
        assert added == sum(sum(sum(c.values()) for c in demo_seed._weekly_check_plan(w).values()) for w in range(12))
        assert db.query(InstitutionObservation).filter_by(is_simulated=True).count() == added
        assert demo_seed.seed_vit_checks(db) == 0
    finally:
        db.close()
        engine.dispose()


def test_rows_older_than_24_months_are_purged(api_client):
    from app.models.models import InstitutionObservation
    from app.services.institution_dashboard import get_institution, purge_old_observations
    gen, db = _db()
    try:
        institution = get_institution(db)
        today = date(2026, 11, 14)
        old_week = f"{(today - timedelta(weeks=110)).isocalendar()[0]}-W{(today - timedelta(weeks=110)).isocalendar()[1]:02d}"
        kept_week = f"{(today - timedelta(weeks=100)).isocalendar()[0]}-W{(today - timedelta(weeks=100)).isocalendar()[1]:02d}"
        for week in (old_week, kept_week):
            db.add(InstitutionObservation(institution_id=institution.id, iso_week=week, band="high risk",
                                          scam_category="other"))
        db.commit()
        purge_old_observations(db, today)
        db.commit()
        weeks = {r.iso_week for r in db.query(InstitutionObservation).filter(
            InstitutionObservation.iso_week.in_([old_week, kept_week]))}
        assert weeks == {kept_week}
        db.query(InstitutionObservation).filter_by(iso_week=kept_week, scam_category="other").delete()
        db.commit()
    finally:
        gen.close()
