"""Simulated reports (fixtures/demo/simulated_senders.csv), DEMO_MODE only.

Sample letter scam_shared_upi_corvane.txt, expected band derived by hand before running
(DEMO_MODE=1, seeded reports, corvanestaffing.example NOT a demo domain -> NXDOMAIN):
  payment demand 'security deposit' +65 (no urgency terms)
  contact domain fails (NXDOMAIN)    +30
  no GSTIN/CIN/LLPIN                 +20
  UPI careerdesk.fees@ybl reported by 6 seeded reports (3-9 bucket) +25; no template match
  total 140 -> capped at 100 -> high risk
"""
import uuid

import pytest

from app.services import community_reports as cr
from app.services import demo_seed
from conftest import DEMO_DIR

PEPPER = "vit-demo-seed-test-pepper"


@pytest.fixture
def seeded(api_client, monkeypatch):
    from app.db.database import get_db
    from app.main import app
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("INDICATOR_PEPPER", PEPPER)
    gen = app.dependency_overrides[get_db]()
    db = next(gen)
    demo_seed.seed_vit_simulation(db)
    yield db
    gen.close()


def _seed_ids():
    return {str(uuid.uuid5(demo_seed.SEED_NAMESPACE, f"{s['key']}:{i}"))
            for s in demo_seed.load_senders() for i in range(s["reports"])}


def test_simulation_definition_is_fictional_and_shaped_as_specified():
    senders = demo_seed.load_senders()
    assert 7 <= len(senders) <= 8
    assert sum(s["reports"] for s in senders) == sum(demo_seed.WEEKLY_REPORTS)
    counts = sorted(s["reports"] for s in senders)
    assert counts.count(2) == 1                                   # one sender that must not appear
    assert sum(1 for c in counts if 8 <= c <= 12) == 2            # a couple of big senders
    assert sum(1 for c in counts if 3 <= c <= 6) >= 4             # mostly 3-6
    assert sum(1 for s in senders if s["disputed"]) == 1
    for s in senders:
        if s["indicator_type"] in ("domain", "email"):
            domain = s["value"].rsplit("@", 1)[-1]
            assert domain.endswith(".example") or domain == "gmail.com", s["value"]
    assert {s["indicator_type"] for s in senders} >= {"email", "domain", "upi", "phone"}


def test_seeding_is_idempotent_and_demo_flagged(seeded):
    from app.models.models import CommunityReport, InstitutionObservation
    ids = _seed_ids()
    reports = seeded.query(CommunityReport).filter(CommunityReport.id.in_(ids)).all()
    assert len(reports) == len(ids) == 45
    assert all(r.is_demo and r.consent_version == cr.CONSENT_VERSION for r in reports)
    assert seeded.query(InstitutionObservation).filter(InstitutionObservation.report_id.in_(ids)).count() == 45
    assert demo_seed.seed_vit_simulation(seeded) == 0              # second run adds nothing


def test_seeding_refuses_outside_demo_mode(api_client, monkeypatch):
    from app.db.database import get_db
    from app.main import app
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.setenv("INDICATOR_PEPPER", PEPPER)
    gen = app.dependency_overrides[get_db]()
    db = next(gen)
    try:
        with pytest.raises(RuntimeError, match="DEMO_MODE"):
            demo_seed.seed_vit_simulation(db)
    finally:
        gen.close()


def test_dashboard_shows_seeded_senders_in_demo_mode(seeded, api_client):
    body = api_client.get("/trends/dashboard").json()
    shown = {s["indicator"]: s for s in body["top_senders"]}
    expected = {cr.masked(s["indicator_type"], s["value"]): s for s in demo_seed.load_senders()}
    for masked_value, sender in expected.items():
        if sender["reports"] < 3:
            assert masked_value not in shown                      # the 2-report sender never appears
        else:
            assert shown[masked_value]["reports"] == sender["reports"]
            assert shown[masked_value]["most_common_category"] == sender["category"]
            assert (shown[masked_value]["dispute_status"] is not None) == sender["disputed"]
    assert shown["pl•••@gmail.com"]["reports"] == 12
    assert shown["nimbuslearn-hiring.example"]["dispute_status"] == "disputed by the company, under review"
    assert all("placement.desk.vit" not in s["indicator"] for s in body["top_senders"])

    # The chart includes the simulated reports' weeks. (Exact seeded row counts are pinned in
    # test_seeding_is_idempotent_and_demo_flagged and tests/test_demo_checks.py; the chart total
    # itself also grows with every check made in demo mode, so it has no fixed bound.)
    weeks = body["weeks"]
    assert any(isinstance(c["count"], int) for c in body["by_week_band"])        # some weeks are visible
    first_weeks = {s["first_week"] for s in body["top_senders"]}
    assert first_weeks <= set(weeks)


def test_seeded_data_hidden_outside_demo_mode(seeded, api_client, monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    body = api_client.get("/trends/dashboard").json()
    assert "pl•••@gmail.com" not in {s["indicator"] for s in body["top_senders"]}
    csv_text = api_client.get("/trends/senders.csv").text
    assert "gmail.com" not in csv_text and "nimbuslearn" not in csv_text


def test_corvane_sample_matches_seeded_sender(seeded, api_client):
    text = (DEMO_DIR / "scam_shared_upi_corvane.txt").read_text(encoding="utf-8")
    body = api_client.post("/analyze", data={"text": text}).json()
    community = next(c for c in body["checks"] if c["check_name"] == "community_reports")
    assert community["status"] == "fail"
    assert "reported by 3+ students" in community["details"]
    assert (body["overall_risk_score"], body["risk_band"]) == (100.0, "high risk")
    dashboard = api_client.get("/trends/dashboard").json()
    # The same sender, in the same masked form, is on the scam-trends page and in the report flow.
    assert "careerd•••@ybl" in {s["indicator"] for s in dashboard["top_senders"]}
    assert any(i["masked"] == "careerd•••@ybl" for i in body["reportable_indicators"])
