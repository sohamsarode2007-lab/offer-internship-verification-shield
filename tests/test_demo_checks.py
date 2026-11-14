"""Simulated VIT Pune CHECKS that fill the 12-week chart (DEMO_MODE only).

The senders table stays based on the 45 simulated reports; the chart and category table
include these checks plus the reports' observations.
"""
import pytest

from app.services import demo_seed
from app.services.institution_dashboard import BANDS

PEPPER = "vit-demo-seed-test-pepper"


def _plan_totals():
    return [sum(sum(c.values()) for c in demo_seed._weekly_check_plan(w).values()) for w in range(12)]


def test_check_plan_shape():
    total = sum(_plan_totals())
    assert 300 <= total <= 500
    by_band = {band: sum(sum(demo_seed._weekly_check_plan(w)[band].values()) for w in range(12)) for band in BANDS}
    # Mostly insufficient evidence and likely legitimate, with a steady share of high risk.
    assert by_band["insufficient evidence, verify manually"] > by_band["high risk"]
    assert by_band["likely legitimate"] > by_band["high risk"] * 0.6
    high = [sum(demo_seed._weekly_check_plan(w)["high risk"].values()) for w in range(12)]
    assert sum(high[-4:]) > sum(high[:4]) * 1.5                          # visible upward trend
    for w in range(12):
        plan = demo_seed._weekly_check_plan(w)
        assert set(plan["likely legitimate"]) == {"no_red_flags"}         # legit checks have no red flags
        assert all(v >= 0 for band in plan.values() for v in band.values())


@pytest.fixture
def demo_db(api_client, monkeypatch):
    from app.db.database import get_db
    from app.main import app
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("INDICATOR_PEPPER", PEPPER)
    gen = app.dependency_overrides[get_db]()
    db = next(gen)
    demo_seed.seed_vit_simulation(db)
    demo_seed.seed_vit_checks(db)
    yield db
    gen.close()


def test_checks_are_idempotent_and_demo_only(demo_db, monkeypatch):
    from app.models.models import InstitutionObservation
    checks = demo_db.query(InstitutionObservation).filter(InstitutionObservation.is_simulated.is_(True),
                                                          InstitutionObservation.report_id.is_(None))
    assert checks.count() == sum(_plan_totals())
    assert demo_seed.seed_vit_checks(demo_db) == 0
    assert checks.count() == sum(_plan_totals())
    monkeypatch.delenv("DEMO_MODE")
    with pytest.raises(RuntimeError, match="DEMO_MODE"):
        demo_seed.seed_vit_checks(demo_db)


def test_chart_mostly_visible_with_two_deliberate_small_cells(demo_db, api_client):
    body = api_client.get("/placement-cell/dashboard").json()
    cells = body["by_week_band"]
    small = [(c["week"], c["band"]) for c in cells if c["count"] == "<5"]
    assert len(cells) == 36
    assert 2 <= len(small) <= 3
    weeks = body["weeks"]
    assert (weeks[0], "likely legitimate") in small and (weeks[1], "high risk") in small
    category_cells = body["by_week_category"]
    visible = sum(isinstance(c["count"], int) for c in category_cells)
    assert visible > len(category_cells) / 2                              # most category cells >= 5


def test_sections_agree(demo_db, api_client):
    body = api_client.get("/placement-cell/dashboard").json()
    high = {c["week"]: c["count"] for c in body["by_week_band"] if c["band"] == "high risk"}
    # Every week in which a listed sender was last reported shows a visible high-risk bar.
    for sender in body["top_senders"]:
        assert isinstance(high[sender["last_week"]], int) and high[sender["last_week"]] >= 5, sender
    # Week totals in the chart equal week totals in the category table (same observations).
    for week in body["weeks"]:
        by_band = [c["count"] for c in body["by_week_band"] if c["week"] == week]
        by_cat = [c["count"] for c in body["by_week_category"] if c["week"] == week]
        if all(isinstance(n, int) for n in by_band + by_cat):
            assert sum(by_band) == sum(by_cat)
    # The senders table is unchanged by the simulated checks (45 reports, 7 senders shown).
    assert len(body["top_senders"]) == 7
    assert sum(s["reports"] for s in body["top_senders"]) == 43           # 45 minus the 2-report sender


def test_simulated_checks_hidden_outside_demo_mode(demo_db, api_client, monkeypatch):
    monkeypatch.delenv("DEMO_MODE")
    body = api_client.get("/placement-cell/dashboard").json()
    weeks = body["weeks"]
    # An older week: real checks made by other tests only ever land in the current week.
    legit_older = next(c["count"] for c in body["by_week_band"]
                       if c["week"] == weeks[-6] and c["band"] == "likely legitimate")
    assert legit_older == "<5"
