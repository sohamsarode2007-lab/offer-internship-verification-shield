"""Link-pattern notes: structural only, no network, no score effect, never echo the link."""
import socket

import pytest

from app.services import fact_extraction, plausibility, risk_scoring
from app.services.url_evidence import url_flags, url_notes


@pytest.mark.parametrize("text, flag", [
    ("Confirm here: https://bit.ly/3abcXYZ", "shortener"),
    ("Confirm here: www.tinyurl.com/x1", "shortener"),
    ("Visit https://xn--acme-9ua.example/login", "punycode"),
    ("Visit https://acmе.example/login", "homoglyph"),   # Cyrillic 'е'
    ("Visit http://203.0.113.9/apply", "ip_literal"),
    ("Visit https://careers.acme.example@evil.example/login", "userinfo"),
])
def test_each_pattern_is_detected(text, flag):
    assert flag in url_flags(text)


@pytest.mark.parametrize("text", [
    "Apply at https://careers.acme.example/jobs/123.",
    "Our site: www.acme.example, mail hr@acme.example.",
    "Read https://docs.python.org/3/ and https://en.wikipedia.org/wiki/Hindi",
    "No links here.",
    "https://bit.ly.acme.example/x",   # a shortener name inside someone else's domain is not a shortener
])
def test_ordinary_links_have_no_flags(text):
    assert url_flags(text) == []


def test_notes_never_repeat_the_link_or_domain():
    notes = url_notes("Go to https://bit.ly/secretpath and https://careers.acme.example@evil.example/x")
    assert notes and all("bit.ly" not in n and "evil" not in n and "secretpath" not in n for n in notes)


def test_no_network_is_touched(monkeypatch):
    def boom(*a, **k): raise AssertionError("network used")
    monkeypatch.setattr(socket, "getaddrinfo", boom)
    monkeypatch.setattr(socket.socket, "connect", boom)
    assert url_flags("https://bit.ly/x https://acmе.example")


def test_collect_notes_includes_link_notes_and_scoring_is_unaffected():
    assert any("link shortener" in n for n in plausibility.collect_notes("Apply: https://bit.ly/abc"))
    base = "Acme Data Solutions Pvt Ltd; Contact hr@acmedata.example."
    f1, f2 = fact_extraction.extract_facts(base), fact_extraction.extract_facts(base + " https://bit.ly/abc")
    checks = [{"check_name": "domain_verification", "status": "pass"}]
    assert risk_scoring.calculate_risk_score(checks, facts=f1)["overall_risk_score"] == \
        risk_scoring.calculate_risk_score(checks, facts=f2)["overall_risk_score"]
