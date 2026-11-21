"""Udyam self-check: shown only for a well-formed number, never when a payment demand was found."""
import pytest

from app.services import fact_extraction
from app.services.self_checks import UDYAM_VERIFY_URL, build_self_checks as build

NO_PAYMENT = [{"check_name": "payment_detection", "status": "pass"}]
PAYMENT = [{"check_name": "payment_detection", "status": "fail"}]


def facts(text):
    return fact_extraction.extract_facts(text)


def test_valid_udyam_number_gets_a_self_check_with_the_fixed_official_link():
    out = build(facts("Acme Data Solutions Pvt Ltd; Udyam Registration Number UDYAM-MH-12-1234567."), NO_PAYMENT)
    assert [c["id"] for c in out] == ["udyam"]
    assert out[0]["number"] == "UDYAM-MH-12-1234567" and out[0]["url"] == UDYAM_VERIFY_URL
    assert out[0]["url"].startswith("https://udyamregistration.gov.in/")
    assert "not verified" in out[0]["why"] and len(out[0]["steps"]) >= 3 and out[0]["caution"]


def test_lowercase_and_spaced_number_is_normalised():
    out = build(facts("Udyam: udyam-mh-12-1234567"), NO_PAYMENT)
    assert out and out[0]["number"] == "UDYAM-MH-12-1234567"


@pytest.mark.parametrize("text", [
    "No registration number here.",
    "Udyam Registration Number UDYAM-MH-12-123",       # too short: the structural check already fails it
    "Udyam Registration Number UDYAM-M-12-1234567",    # bad state code
])
def test_no_self_check_without_a_well_formed_number(text):
    assert build(facts(text), NO_PAYMENT) == []


def test_no_self_check_when_a_payment_demand_was_found():
    assert build(facts("Udyam Registration Number UDYAM-MH-12-1234567."), PAYMENT) == []


def test_link_never_comes_from_offer_text():
    out = build(facts("Udyam UDYAM-MH-12-1234567 see https://evil.example/verify"), NO_PAYMENT)
    assert out[0]["url"] == UDYAM_VERIFY_URL and "evil" not in str(out)


def test_api_returns_self_checks_and_they_do_not_change_the_score(api_client):
    base = "Acme Data Solutions Pvt Ltd; Contact hr@acmedata.example."
    with_udyam = api_client.post("/analyze", data={"text": base + " Udyam Registration Number UDYAM-MH-12-1234567."}).json()
    assert with_udyam["self_checks"][0]["id"] == "udyam"
    assert with_udyam["self_checks"][0]["number"] == "UDYAM-MH-12-1234567"
    plain = api_client.post("/analyze", data={"text": base}).json()
    assert plain["self_checks"] == []
