import json
from datetime import datetime, timedelta, timezone

import pytest

from app.services import domain_verification as dv
from app.services import rdap

BOOTSTRAP = {"services": [[["example", "test"], ["https://rdap.registry.example/v1/"]],
                          [["plain"], ["http://insecure.example/", "https://rdap.plain.example/"]]]}


def registration(days_ago):
    when = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"events": [{"eventAction": "last changed", "eventDate": "2020-01-01T00:00:00Z"},
                       {"eventAction": "registration", "eventDate": when}]}


PAYLOAD = {}


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    monkeypatch.setattr(rdap, "_bootstrap", (0.0, {}))
    monkeypatch.setattr(rdap, "_cache", {})
    monkeypatch.delenv("RDAP_LOOKUPS", raising=False)


@pytest.fixture
def server(monkeypatch):
    calls = []

    def fake_request(method, scheme, host, path, **kwargs):
        calls.append((scheme, host, path))
        if host == rdap.BOOTSTRAP_HOST:
            return 200, None, None, json.dumps(BOOTSTRAP).encode()
        return 200, None, None, json.dumps(PAYLOAD["body"]).encode()

    PAYLOAD["body"] = registration(3)
    monkeypatch.setattr(rdap.safe_fetch, "request", fake_request)
    return calls


def test_registration_date_comes_from_the_registrys_own_server(server):
    created = rdap.creation_date("fresh-company.example")
    assert (datetime.now(timezone.utc) - created).days == 3
    assert server[1] == ("https", "rdap.registry.example", "/v1/domain/fresh-company.example")


def test_only_the_domain_is_sent_and_only_https_servers_are_used(server):
    rdap.creation_date("fresh-company.plain")
    assert server[1][1] == "rdap.plain.example"
    sent = " ".join(" ".join(call) for call in server)
    assert "?" not in sent and "@" not in sent


def test_a_second_lookup_for_the_same_domain_is_served_from_the_cache(server):
    rdap.creation_date("fresh-company.example")
    rdap.creation_date("FRESH-company.example.")
    assert len(server) == 2   # one bootstrap fetch, one registry query


@pytest.mark.parametrize("bad", ["", "no-dot", "a b.example", "x.example/../etc", "user@x.example", "x.example?a=1", "-"])
def test_odd_input_makes_no_request(server, bad):
    assert rdap.creation_date(bad) is None
    assert server == []


def test_tld_without_a_server_and_http_errors_give_none(monkeypatch, server):
    assert rdap.creation_date("x.unknowntld") is None
    monkeypatch.setattr(rdap.safe_fetch, "request", lambda *a, **k: (404, None, None, b""))
    assert rdap.creation_date("gone.example") is None


def test_network_errors_and_garbage_give_none_and_are_remembered_briefly(monkeypatch, server):
    def boom(*a, **k):
        raise OSError("down")
    monkeypatch.setattr(rdap.safe_fetch, "request", boom)
    assert rdap.creation_date("down.example") is None
    monkeypatch.setattr(rdap.safe_fetch, "request", lambda *a, **k: (200, None, None, b"not json"))
    assert rdap.creation_date("down.example") is None   # cached miss, still None, no exception


def test_event_without_a_registration_date_gives_none(server):
    PAYLOAD["body"] = {"events": [{"eventAction": "last changed", "eventDate": "2020-01-01T00:00:00Z"}]}
    assert rdap.creation_date("odd.example") is None


def test_switch_off_makes_no_request(monkeypatch, server):
    monkeypatch.setenv("RDAP_LOOKUPS", "0")
    assert rdap.creation_date("fresh-company.example") is None
    assert server == []


def test_domain_age_uses_rdap_first_and_falls_back_to_whois(monkeypatch):
    young = datetime.now(timezone.utc) - timedelta(days=3)
    old = datetime.now(timezone.utc) - timedelta(days=900)
    monkeypatch.setattr(dv, "_rdap_creation_date", lambda d: young)
    monkeypatch.setattr(dv, "_whois_creation_date", lambda d: old)
    assert dv.check_domain_age("x.example")["status"] == "fail"          # RDAP wins
    monkeypatch.setattr(dv, "_rdap_creation_date", lambda d: None)
    assert dv.check_domain_age("x.example")["status"] == "pass"          # WHOIS used when RDAP has nothing
    monkeypatch.setattr(dv, "_whois_creation_date", lambda d: None)
    assert dv.check_domain_age("x.example")["status"] == "unknown"       # neither: not counted as a pass
