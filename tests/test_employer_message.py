"""Employer-verification message: fixed wording, no claimed contact, none when a payment was demanded."""
from app.services import fact_extraction
from app.services.employer_message import build_employer_message as build

NO_PAYMENT = [{"check_name": "payment_detection", "status": "pass"}]
PAYMENT = [{"check_name": "payment_detection", "status": "fail"}]


def facts(text):
    return fact_extraction.extract_facts(text)


def test_message_names_the_company_and_asks_the_three_questions():
    out = build(facts("Offer from Quillmere Software Pvt Ltd for a trainee role. Contact hr@quillmere.example."), NO_PAYMENT)
    assert out and "Quillmere Software Pvt Ltd" in out["body"]
    assert out["body"].count("\n1. ") == 1 and "\n2. " in out["body"] and "\n3. " in out["body"]
    assert "I have not paid anything" in out["body"]


def test_it_never_claims_a_verified_contact_or_uses_offer_contact_details():
    out = build(facts("Quillmere Software Pvt Ltd. Write to hr@quillmere.example or call +91 98765 43210."), NO_PAYMENT)
    text = str(out)
    assert "hr@quillmere.example" not in text and "98765" not in text
    assert "verified" not in text.lower().replace("does not know", "")
    assert "Do not use any link, phone number or email address from the offer" in text


def test_blank_to_fill_in_when_no_company_name_is_found():
    out = build(facts("Selected for an internship. Details to follow."), NO_PAYMENT)
    assert out and "your company" in out["body"]


def test_nothing_is_offered_when_a_payment_demand_was_found():
    assert build(facts("Quillmere Software Pvt Ltd. Pay a fee."), PAYMENT) is None


def test_api_returns_it_for_a_non_payment_offer_and_not_for_a_fee_demand(api_client):
    ok = api_client.post("/analyze", data={"text": "Quillmere Software Pvt Ltd trainee role. Contact hr@quillmere.example."}).json()
    assert ok["employer_message"]["subject"]
    scam = api_client.post("/analyze", data={"text": "Pay a refundable security deposit of Rs 2000 to UPI fees@ybl to join."}).json()
    assert scam["employer_message"] is None
