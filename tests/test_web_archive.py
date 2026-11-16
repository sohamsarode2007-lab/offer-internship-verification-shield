"""Internet Archive first-seen note. Offline: the HTTP call is replaced."""
import json

import pytest

from app.services import domain_verification as dv, web_archive


@pytest.fixture
def archive(monkeypatch):
    monkeypatch.setenv("INFRA_AGE_LOOKUPS", "1")
    calls = []

    def install(payload=None, exc=None):
        def fake_open(url):
            calls.append(url)
            if exc:
                raise exc
            return json.dumps(payload).encode()
        monkeypatch.setattr(web_archive, "_open", fake_open)
    install.calls = calls
    return install


def test_earliest_capture_month_is_returned(archive):
    archive([["timestamp"], ["20190305123456"]])
    assert web_archive.first_capture_month("emberlake.example") == "2019-03"
    assert "url=emberlake.example" in archive.calls[0]


@pytest.mark.parametrize("payload", [[], [["timestamp"]], [["timestamp"], ["notadate"]], {"x": 1}, "text"])
def test_empty_or_odd_payloads_return_none(archive, payload):
    archive(payload)
    assert web_archive.first_capture_month("emberlake.example") is None


@pytest.mark.parametrize("failure", [TimeoutError("slow"), OSError("blocked")])
def test_network_failure_returns_none(archive, failure):
    archive(exc=failure)
    assert web_archive.first_capture_month("emberlake.example") is None


def test_disabled_by_default_makes_no_request(monkeypatch, archive):
    monkeypatch.delenv("INFRA_AGE_LOOKUPS")
    archive([["timestamp"], ["20190305123456"]])
    assert web_archive.first_capture_month("emberlake.example") is None
    assert archive.calls == []


def _stub_dns(monkeypatch, age_status):
    ok = {"check_name": "mx_records", "status": "pass", "explanation": "MX present."}
    monkeypatch.setattr(dv, "check_mx_records", lambda host: ok)
    monkeypatch.setattr(dv, "check_spf_record", lambda host: {"check_name": "spf", "status": "pass", "explanation": "SPF."})
    monkeypatch.setattr(dv, "check_dmarc_record", lambda host: {"check_name": "dmarc", "status": "pass", "explanation": "DMARC."})
    monkeypatch.setattr(dv, "check_domain_age", lambda d: {"check_name": "domain_age", "status": age_status, "explanation": "Age unknown."})


def test_note_added_only_when_whois_age_is_unknown(monkeypatch, archive):
    _stub_dns(monkeypatch, "unknown")
    archive([["timestamp"], ["20190305123456"]])
    result = dv.verify_domain({"sender_domain": "emberlake.example"})
    assert result["status"] == "pass"
    assert "earliest saved copy of 'emberlake.example' is from 2019-03" in result["details"]


def test_no_lookup_when_whois_age_is_known(monkeypatch, archive):
    _stub_dns(monkeypatch, "pass")
    archive([["timestamp"], ["20190305123456"]])
    result = dv.verify_domain({"sender_domain": "emberlake.example"})
    assert "Internet Archive" not in result["details"] and archive.calls == []
