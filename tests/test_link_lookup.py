"""Opt-in link lookups: consent gate, minimised addresses, Web Risk result mapping, redirects. No real network."""
import ssl

import pytest

from app.services import link_lookup as ll, request_budget, safe_fetch


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("LINK_LOOKUPS", "1")
    monkeypatch.setenv("WEB_RISK_API_KEY", "test-key")
    request_budget.reset()


TEXT = "Apply at https://jobs.quillmere.example/apply?email=a@b.com&id=12345678901#top now"


def test_minimise_drops_query_fragment_and_pii_paths():
    assert ll.minimise("https://jobs.quillmere.example/apply?email=a@b.com#x") == "https://jobs.quillmere.example/apply"
    assert ll.minimise("https://x.example/rahul@mail.com/offer") == "https://x.example/"
    assert ll.minimise("https://x.example/cand/9876543210") == "https://x.example/"
    assert ll.minimise("https://user:pw@x.example/") is None
    assert ll.minimise("http://192.168.0.1/a") is None
    assert ll.minimise("ftp://x.example/") is None


def test_at_most_three_distinct_links():
    text = " ".join(f"https://s{i}.example/a" for i in range(6)) + " https://s0.example/a"
    assert len(ll.extract_links(text)) == 3


def test_nothing_happens_without_consent_or_operator_switch(monkeypatch):
    monkeypatch.setattr(ll, "_get_json", lambda u: pytest.fail("must not call"))
    monkeypatch.setattr(ll, "_head", lambda u, t=None: pytest.fail("must not visit"))
    assert ll.build_link_checks(TEXT, consent=False) == {"notes": [], "threat_listed": False}
    monkeypatch.delenv("LINK_LOOKUPS")
    assert ll.build_link_checks(TEXT, consent=True) == {"notes": [], "threat_listed": False}


def test_only_minimised_address_is_sent_to_web_risk(monkeypatch):
    sent = []
    monkeypatch.setattr(ll, "_get_json", lambda u: sent.append(u) or {})
    monkeypatch.setattr(ll, "_head", lambda u, t=None: (200, None, None))
    ll.build_link_checks(TEXT, consent=True)
    assert len(sent) == 1
    assert "email" not in sent[0] and "12345678901" not in sent[0] and "%40" not in sent[0]
    assert "quillmere.example%2Fapply" in sent[0] or "quillmere.example" in sent[0]


def test_threat_listed_is_reported(monkeypatch):
    monkeypatch.setattr(ll, "_get_json", lambda u: {"threat": {"threatTypes": ["SOCIAL_ENGINEERING"]}})
    monkeypatch.setattr(ll, "_head", lambda u, t=None: (200, None, None))
    out = ll.build_link_checks(TEXT, consent=True)
    assert out["threat_listed"] is True
    assert any("Web Risk lists" in n and "social engineering" in n for n in out["notes"])


def test_no_match_error_or_no_key_is_only_unknown(monkeypatch):
    monkeypatch.setattr(ll, "_head", lambda u, t=None: (200, None, None))
    monkeypatch.setattr(ll, "_get_json", lambda u: {})
    assert ll.web_risk("https://x.example/")["status"] == "unknown"
    def boom(u):
        raise OSError("down")
    monkeypatch.setattr(ll, "_get_json", boom)
    assert ll.web_risk("https://x.example/")["status"] == "unknown"
    monkeypatch.delenv("WEB_RISK_API_KEY")
    assert ll.web_risk("https://x.example/")["status"] == "unknown"
    assert ll.build_link_checks(TEXT, consent=True)["notes"] == []  # nothing flagged, so never a "safe" note


def test_redirect_to_other_site_is_noted(monkeypatch):
    hops = {"https://short.example/a": (302, "https://landing.example/x", {"notBefore": "Jan  1 00:00:00 2020 GMT"}),
            "https://landing.example/x": (200, None, {"notBefore": "Jan  1 00:00:00 2020 GMT"})}
    monkeypatch.setattr(ll, "_head", lambda u, t=None: hops[u])
    monkeypatch.setattr(ll, "_get_json", lambda u: {})
    out = ll.build_link_checks("see https://short.example/a", consent=True)
    assert any("redirects to a different site, 'landing.example'" in n for n in out["notes"])


def test_redirect_loop_is_bounded(monkeypatch):
    calls = []
    monkeypatch.setattr(ll, "_head", lambda u, t=None: calls.append(u) or (302, "https://loop.example/b", None))
    result = ll.follow("https://loop.example/a")
    assert len(calls) == ll.MAX_HOPS + 1 and result["hops"] == ll.MAX_HOPS


def test_bad_certificate_and_new_certificate(monkeypatch):
    def bad(u, t=None):
        raise ssl.SSLCertVerificationError("bad")
    monkeypatch.setattr(ll, "_head", bad)
    assert ll.follow("https://x.example/")["tls"] == "invalid"
    import time
    fresh = time.strftime("%b %d %H:%M:%S %Y GMT", time.gmtime(time.time() - 86400))
    monkeypatch.setattr(ll, "_head", lambda u, t=None: (200, None, {"notBefore": fresh}))
    assert ll.follow("https://x.example/")["cert_age_days"] == 1


def test_non_public_host_is_never_visited(monkeypatch):
    def refuse(u, t=None):
        raise safe_fetch.UnsafeTarget("name resolves to a non-public address")
    monkeypatch.setattr(ll, "_head", refuse)
    assert ll.follow("https://internal.example/")["stopped"] is True


def test_links_are_checked_in_parallel_under_one_deadline(monkeypatch):
    import time
    monkeypatch.setattr(ll, "OVERALL_DEADLINE_SECONDS", 1.0)
    monkeypatch.setattr(ll, "_get_json", lambda u: {})
    monkeypatch.setattr(ll, "_head", lambda u, t=None: (time.sleep(5), 200, None, None)[1:])
    started = time.monotonic()
    out = ll.build_link_checks(" ".join(f"https://s{i}.example/a" for i in range(3)), consent=True)
    assert time.monotonic() - started < 3.5          # three 5 s visits did not add up to 15 s
    assert out == {"notes": [], "threat_listed": False}


def test_visits_stop_when_the_daily_visit_budget_is_spent(monkeypatch):
    monkeypatch.setenv("LINK_VISIT_DAILY_BUDGET", "0")
    monkeypatch.setattr(ll, "_head", lambda u, t=None: pytest.fail("must not visit"))
    assert ll.follow("https://x.example/")["stopped"] is True


def test_api_requires_consent_field(api_client, monkeypatch):
    seen = []
    monkeypatch.setattr(ll, "_get_json", lambda u: seen.append(u) or {"threat": {"threatTypes": ["MALWARE"]}})
    monkeypatch.setattr(ll, "_head", lambda u, t=None: (200, None, None))
    body = {"text": "Join us. Apply at https://jobs.quillmere.example/apply today."}
    r = api_client.post("/analyze", data=body)
    assert r.status_code == 200 and not seen
    r = api_client.post("/analyze", data={**body, "link_lookups": "true"})
    assert seen and any("Web Risk lists" in x["text"] for x in r.json()["reasons"])
    assert any(a["id"] == "links" for a in r.json()["safety_actions"])


def test_link_checks_have_a_per_connection_hourly_allowance(api_client, monkeypatch):
    import app.api.routes.analyze as az
    monkeypatch.setattr(az, "LINK_CHECKS_PER_HOUR", 2)
    seen = []
    monkeypatch.setattr(ll, "_get_json", lambda u: seen.append(u) or {})
    monkeypatch.setattr(ll, "_head", lambda u, t=None: (200, None, None))
    body = {"text": "Apply at https://jobs.quillmere.example/apply today.", "link_lookups": "true"}
    for _ in range(2):
        api_client.post("/analyze", data=body)
    n = len(seen)
    r = api_client.post("/analyze", data=body)
    assert len(seen) == n                              # third request made no outbound lookups
    assert r.status_code == 200
    assert any("hourly allowance" in x["text"] for x in r.json()["reasons"])
    # requests that did not ask for link checks never spend the allowance
    request_budget.reset()
    for _ in range(5):
        api_client.post("/analyze", data={"text": body["text"]})
    assert api_client.post("/analyze", data=body).status_code == 200 and len(seen) > n


def test_config_endpoint_reports_switch(api_client, monkeypatch):
    assert api_client.get("/config").json() == {"link_lookups": True}
    monkeypatch.delenv("LINK_LOOKUPS")
    assert api_client.get("/config").json() == {"link_lookups": False}
