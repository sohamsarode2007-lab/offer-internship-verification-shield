"""Source freshness panel and the daily request budget. Fictional data only."""
import sqlite3
from datetime import date

import pytest

from app.services import link_lookup, request_budget, source_freshness as sf

TODAY = date(2026, 11, 21)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    request_budget.reset()
    for var in ("MCA_DB_PATH", "WEB_RISK_API_KEY", "LINK_LOOKUPS", "WEB_RISK_DAILY_BUDGET"):
        monkeypatch.delenv(var, raising=False)


def make_db(path, loaded, source="MCA_CSV"):
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE registry_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.executemany("INSERT INTO registry_metadata VALUES (?, ?)",
                       [("source", source), ("loaded_at", loaded), ("row_count", "5")])


def registry(monkeypatch, tmp_path, loaded, source="MCA_CSV"):
    db = tmp_path / "m.sqlite3"
    db.unlink(missing_ok=True)
    make_db(db, loaded, source)
    monkeypatch.setenv("MCA_DB_PATH", str(db))
    return sf._registry(TODAY)


def test_missing_registry_is_unknown_not_fresh(monkeypatch, tmp_path):
    monkeypatch.setenv("MCA_DB_PATH", str(tmp_path / "none.sqlite3"))
    assert sf._registry(TODAY)["status"] == "unknown"


def test_recent_snapshot_is_current(monkeypatch, tmp_path):
    r = registry(monkeypatch, tmp_path, "2026-11-01T00:00:00+00:00")
    assert (r["status"], r["age_days"], r["updated"]) == ("current", 20, "2026-11-01")


def test_old_snapshot_is_stale_at_91_days_not_90(monkeypatch, tmp_path):
    assert registry(monkeypatch, tmp_path, "2026-08-23T00:00:00+00:00")["status"] == "current"  # 90 days
    assert registry(monkeypatch, tmp_path, "2026-08-22T00:00:00+00:00")["status"] == "stale"    # 91 days


def test_synthetic_snapshot_is_labelled_demo(monkeypatch, tmp_path):
    r = registry(monkeypatch, tmp_path, "2026-11-20T00:00:00+00:00", "SYNTHETIC")
    assert r["status"] == "demo" and "not real company records" in r["detail"]


def test_snapshot_without_metadata_is_unknown(monkeypatch, tmp_path):
    db = tmp_path / "legacy.sqlite3"
    sqlite3.connect(db).close()
    monkeypatch.setenv("MCA_DB_PATH", str(db))
    assert sf._registry(TODAY)["status"] == "unknown"


def test_advisories_report_oldest_page_and_staleness(monkeypatch):
    monkeypatch.setattr(sf.brand_advisories, "load_advisories",
                        lambda: ({"retrieved": "2026-11-15"}, {"retrieved": "2026-03-01"}))
    a = sf._advisories(TODAY)
    assert a["updated"] == "2026-03-01" and a["status"] == "stale"
    monkeypatch.setattr(sf.brand_advisories, "load_advisories", lambda: ())
    assert sf._advisories(TODAY)["status"] == "unknown"


def test_build_has_no_secrets(monkeypatch):
    monkeypatch.setenv("WEB_RISK_API_KEY", "super-secret-key")
    out = str(sf.build_sources(TODAY))
    assert "super-secret-key" not in out and "'web_risk_key_set': True" in out


def test_budget_blocks_after_limit_and_resets_next_day(monkeypatch):
    monkeypatch.setenv("WEB_RISK_DAILY_BUDGET", "2")
    assert request_budget.try_spend("web_risk") and request_budget.try_spend("web_risk")
    assert request_budget.try_spend("web_risk") is False
    assert request_budget.used("web_risk") == 2
    monkeypatch.setattr(request_budget, "_today", lambda: "2099-01-01")
    assert request_budget.try_spend("web_risk") is True


def test_web_risk_is_skipped_when_budget_spent(monkeypatch):
    monkeypatch.setenv("WEB_RISK_API_KEY", "k")
    monkeypatch.setenv("WEB_RISK_DAILY_BUDGET", "0")
    monkeypatch.setattr(link_lookup, "_get_json", lambda u: pytest.fail("must not call"))
    assert link_lookup.web_risk("https://x.example/")["status"] == "unknown"


def test_sources_endpoint(api_client):
    body = api_client.get("/sources").json()
    assert body["scoring_model"] == "rule_based_v2"
    assert {s["id"] for s in body["sources"]} == {"company_registry", "employer_advisories"}
    assert body["request_budgets"][0]["id"] == "web_risk"
