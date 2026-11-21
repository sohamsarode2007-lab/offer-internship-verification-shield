"""Evidence metadata: traceable source, score effect and confidence; unknowns are never confident."""
from datetime import datetime, timezone

from app.services.evidence_meta import build_evidence_meta as build

NOW = datetime(2026, 11, 19, 9, 0, tzinfo=timezone.utc)


def one(check_name, status, details=""):
    return build([{"check_name": check_name, "status": status, "details": details}], NOW)[0]


def test_pass_and_fail_carry_source_and_a_confidence():
    r = one("domain_verification", "fail")
    assert (r["source"], r["affects"], r["confidence"]) == ("dns_lookup", "score", "medium")
    assert r["checked_at"] == "2026-11-19T09:00:00Z" and r["rule_version"] == "rule_based_v2"


def test_payment_demand_is_a_safety_floor():
    assert one("payment_detection", "fail")["affects"] == "safety_floor"
    assert one("payment_detection", "pass")["affects"] == "score"


def test_unknown_or_not_applicable_is_never_confident_and_has_no_score_effect():
    for status in ("insufficient_information", "not_applicable", "unknown"):
        r = one("gstin_verification", status)
        assert r["confidence"] == "none" and r["affects"] == "context"


def test_demo_fixture_is_labelled_as_not_live():
    r = one("domain_verification", "pass", "[DEMO FIXTURE: synthetic]")
    assert r["source"] == "demo_fixture" and r["freshness"] == "not a live check"


def test_no_values_or_offer_text_in_the_record():
    r = one("scam_text_patterns", "fail", "Wording found: paid tasks; contact someone@scam.example")
    assert "scam.example" not in str(r)


def test_api_returns_one_record_per_check(api_client):
    body = api_client.post("/analyze", data={"text": "A small remote internship is available."}).json()
    assert [m["check_name"] for m in body["evidence_meta"]] == [c["check_name"] for c in body["checks"]]
