"""Requests for bank details or identity documents: moderate warning, never high risk alone."""
import pytest

from app.services import fact_extraction, risk_scoring
from app.services.personal_data_request import detect_personal_data_request as detect


def run(text):
    return detect(fact_extraction.extract_facts(text))


BANK = [
    "Please share your bank account details and IFSC to process the stipend.",
    "Send a cancelled cheque and your account number today.",
    "You must submit your debit card details for verification.",
    "Bank account number is required to confirm your selection.",
    "Apna bank account details bhejiye jaldi.",
]
DOCS = [
    "Kindly send a scan of your Aadhaar card and PAN card.",
    "Please upload your passport size photo and 10th certificate.",
    "Email us your experience certificate and marksheets.",
    "Original documents are needed before we issue the letter.",
    "Apna Aadhaar card share kariye.",
]
NOT = [
    "We never ask candidates for bank details or Aadhaar copies.",
    "Do not share your bank account details with anyone claiming to be from us.",
    "Please bring your original documents on the day of joining.",
    "Submit your Aadhaar and PAN copies after joining, during onboarding.",
    "Your stipend will be credited monthly.",
    "Our office is near the bank; the interview is on Monday.",
    "Bank details are not required at this stage.",
    "Aadhaar card dene ki zaroorat nahi hai.",
]


@pytest.mark.parametrize("text", BANK)
def test_bank_requests_are_found(text):
    r = run(text)
    assert r["status"] == "fail" and r["tier"] == "bank", text


@pytest.mark.parametrize("text", DOCS)
def test_document_requests_are_found(text):
    r = run(text)
    assert r["status"] == "fail" and r["tier"] == "documents", text


@pytest.mark.parametrize("text", NOT)
def test_negated_after_joining_or_unrelated_wording_is_not_a_request(text):
    r = run(text)
    assert r["status"] == "not_applicable", text


def test_both_families_report_bank_tier_and_no_text_is_echoed():
    r = run("Send your bank account details and a copy of your Aadhaar card.")
    assert r["tier"] == "bank" and set(r["families"]) == {"bank", "documents"}
    assert "Aadhaar" not in r["details"] and "account details" not in r["details"].replace("bank account or card details", "")


def check(tier, status="fail"):
    return {"check_name": "personal_data_request", "status": status, "tier": tier, "families": [tier],
            "details": "The text asks for ..."}


BASE = [
    {"check_name": "domain_verification", "status": "pass", "score": 100.0, "details": "ok"},
    {"check_name": "payment_detection", "status": "pass", "score": 100.0, "details": "none"},
]


def score(extra):
    return risk_scoring.calculate_risk_score(BASE + extra, facts={})


def test_bank_request_adds_20_documents_10_and_nothing_when_absent():
    # No usable domain and no registration number: 40 points before this check, clear of the 31 floor.
    base = [{"check_name": "domain_verification", "status": "insufficient_information", "details": "none"}, BASE[1]]
    def total(extra):
        return risk_scoring.calculate_risk_score(base + extra, facts={})["overall_risk_score"]
    none = total([check(None, "not_applicable")])
    assert none == 40
    assert total([check("bank")]) - none == 20
    assert total([check("documents")]) - none == 10


def test_it_is_never_high_risk_by_itself():
    assert score([check("bank")])["risk_band"] != "high risk"


def test_a_payment_demand_still_forces_high_risk_with_or_without_it():
    pay = [{"check_name": "payment_detection", "status": "fail", "score": 0.0, "details": "fee"}]
    for extra in ([], [check("bank")]):
        res = risk_scoring.calculate_risk_score([BASE[0]] + pay + extra, facts={})
        assert res["risk_band"] == "high risk" and res["overall_risk_score"] >= 61


def test_api_shows_the_check_and_the_reason_without_echoing_text(api_client):
    text = "Quillmere Labs trainee role. Please send your bank account details and Aadhaar card copy to hr@quillmere.example."
    r = api_client.post("/analyze", data={"text": text}).json()
    names = {c["check_name"]: c for c in r["checks"]}
    assert names["personal_data_request"]["status"] == "fail"
    assert any("bank details or identity documents" in x["text"] for x in r["reasons"])
    assert "Aadhaar" not in str(names["personal_data_request"])
