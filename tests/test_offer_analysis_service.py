"""The analysis pipeline used without a web request."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.models.models import CheckResult, Offer, VerificationResult
from app.services import offer_analysis as oa

FEE_OFFER = ("You are selected for a trainee role at Quillmere Labs. Pay a refundable registration fee of "
             "Rs 2,500 to UPI fees.desk@ybl today. Write to hr@quillmere-careers.example.")


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_pasted_text_is_read_as_is():
    sub = oa.read_submission("  Hello offer  ", [])
    assert sub.raw_text.strip() == "Hello offer" and sub.email_result is None and sub.file_texts == []


@pytest.mark.parametrize("text,status", [("", 422), ("x" * (oa.MAX_TEXT_CHARS + 1), 413)])
def test_unreadable_or_oversize_submissions_carry_their_http_status(text, status):
    with pytest.raises(oa.SubmissionError) as e:
        oa.read_submission(text, [])
    assert e.value.status_code == status


def test_a_fee_demand_scores_high_risk_and_nothing_is_stored_by_run_checks(db):
    analysis = oa.run_checks(db, oa.read_submission(FEE_OFFER, []))
    assert analysis.scoring["risk_band"] == "high risk" and analysis.scoring["overall_risk_score"] >= 61
    assert {c["check_name"] for c in analysis.check_dicts} >= {"payment_detection", "domain_verification"}
    assert db.query(Offer).count() == 0


def test_store_result_keeps_only_verdict_and_check_rows(db):
    analysis = oa.run_checks(db, oa.read_submission(FEE_OFFER, []))
    schemas = oa.to_check_schemas(analysis.check_dicts)
    offer_id = oa.store_result(db, schemas, analysis.scoring["overall_risk_score"],
                               analysis.scoring["completeness_percentage"], analysis.scoring["risk_band"], "registration_fee")
    assert offer_id is not None
    offer = db.query(Offer).one()
    assert offer.raw_text is None and offer.title is None and offer.company_name is None and offer.file_path is None
    assert db.query(VerificationResult).count() == 1 and db.query(CheckResult).count() == len(schemas)


def test_store_result_failure_returns_none_and_rolls_back(db, monkeypatch):
    analysis = oa.run_checks(db, oa.read_submission(FEE_OFFER, []))
    monkeypatch.setattr(oa.institution_dashboard, "record_check_observation",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert oa.store_result(db, oa.to_check_schemas(analysis.check_dicts), 90, 50, "high risk", "x") is None
    assert db.query(Offer).count() == 0
