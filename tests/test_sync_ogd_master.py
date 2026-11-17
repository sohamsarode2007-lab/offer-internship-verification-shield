"""Bulk sync of the data.gov.in company master. All HTTP is mocked; companies are fictional."""
import json
import sqlite3

import pytest

from scripts import sync_ogd_master as sync

KEY = "test-key-not-a-real-secret"
CINS = ["U74999DL2016PTC298345", "U72900MH2019PTC123456", "L22210MH1995PLC084781"]


def row(cin, name="EMBERLAKE ANALYTICS PRIVATE LIMITED", status="Active"):
    return {"CIN": cin, "CompanyName": name, "CompanyStatus": status, "CompanyRegistrationdate_date": "2016-03-15",
            "RegisteredOfficeAddress": "should never be kept"}


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("DATA_GOV_IN_API_KEY", KEY)
    calls = []
    state = {"rows": [row(c) for c in CINS], "fail_offsets": set()}

    def fake_open(url, timeout):
        calls.append(url)
        query = dict(p.split("=", 1) for p in url.split("?", 1)[1].split("&"))
        offset, limit = int(query["offset"]), int(query["limit"])
        if offset in state["fail_offsets"]:
            raise OSError(f"https://api.data.gov.in/?api-key={KEY}")
        return json.dumps({"total": len(state["rows"]), "records": state["rows"][offset:offset + limit]}).encode()
    monkeypatch.setattr(sync, "_open", fake_open)
    api = type("Api", (), {})()
    api.calls, api.state, api.messages, api.sleeps = calls, state, [], []
    return api


def run(api, tmp_path, **kw):
    return sync.sync(tmp_path / "m.sqlite3", sleep=api.sleeps.append, out=api.messages.append, **kw)


def stored(tmp_path):
    with sqlite3.connect(tmp_path / "m.sqlite3") as db:
        return [r[0] for r in db.execute("SELECT cin FROM mca_companies ORDER BY cin")]


def test_pages_through_everything_and_keeps_only_cin_rows(api, tmp_path):
    api.state["rows"].append({"CIN": "not-a-cin", "CompanyName": "x", "CompanyStatus": "Active"})
    assert run(api, tmp_path, page_size=2) == 0
    assert stored(tmp_path) == sorted(CINS)
    assert len(api.calls) == 2


def test_address_and_other_columns_are_never_stored(api, tmp_path):
    run(api, tmp_path)
    with sqlite3.connect(tmp_path / "m.sqlite3") as db:
        columns = [r[1] for r in db.execute("PRAGMA table_info(mca_companies)")]
    assert columns == ["cin", "company_name", "company_status", "date_of_registration"]


def test_missing_key_makes_no_request(api, tmp_path, monkeypatch):
    monkeypatch.delenv("DATA_GOV_IN_API_KEY")
    assert run(api, tmp_path) == 2
    assert api.calls == []


def test_polite_delay_has_a_floor_and_page_size_a_cap(api, tmp_path):
    run(api, tmp_path, page_size=5000, delay=0.0)
    assert "limit=1000" in api.calls[0]
    assert all(s >= 0.5 for s in api.sleeps)


def test_failure_stops_with_resume_offset_and_never_prints_the_key(api, tmp_path):
    api.state["fail_offsets"] = {2}
    assert run(api, tmp_path, page_size=2) == 1
    text = " ".join(api.messages)
    assert "--start-offset 2" in text and KEY not in text
    assert stored(tmp_path) == sorted(CINS[:2])


def test_resume_from_offset_completes_the_load(api, tmp_path):
    api.state["fail_offsets"] = {2}
    run(api, tmp_path, page_size=2)
    api.state["fail_offsets"] = set()
    assert run(api, tmp_path, page_size=2, start_offset=2) == 0
    assert stored(tmp_path) == sorted(CINS)


def test_transient_failure_is_retried(api, tmp_path, monkeypatch):
    original, attempts = sync._open, []

    def flaky(url, timeout):
        attempts.append(1)
        if len(attempts) == 1:
            raise TimeoutError()
        return original(url, timeout)
    monkeypatch.setattr(sync, "_open", flaky)
    assert run(api, tmp_path) == 0 and len(attempts) >= 2


def test_max_pages_limits_a_trial_run(api, tmp_path):
    assert run(api, tmp_path, page_size=1, max_pages=2) == 0
    assert len(api.calls) == 2 and len(stored(tmp_path)) == 2
