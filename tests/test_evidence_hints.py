"""Evidence hints depend only on which checks could not run."""
from app.services.evidence_hints import build_evidence_hints as build


def c(name, status, **extra):
    return {"check_name": name, "status": status, **extra}


BARE = [c("domain_verification", "not_applicable"), c("gstin_verification", "insufficient_information", identifier_present=False),
        c("payment_detection", "pass"), c("sender_authentication", "not_applicable"), c("scam_text_patterns", "not_applicable")]


def ids(hints):
    return [h["id"] for h in hints]


def test_bare_text_gets_email_domain_and_identifier_hints():
    assert ids(build(BARE)) == ["original_email", "sender_email", "company_identifiers"]


def test_each_hint_has_title_why_and_how():
    assert all(h["title"] and h["why"] and h["how"] for h in build(BARE))


def test_no_hints_when_a_payment_demand_was_found():
    checks = [c("payment_detection", "fail")] + BARE[:1] + BARE[3:]
    assert build(checks) == []


def test_original_email_hint_is_skipped_when_an_eml_was_already_given():
    assert "original_email" not in ids(build(BARE, had_file=True))


def test_identifier_hint_is_skipped_when_an_identifier_was_present():
    checks = [c("gstin_verification", "insufficient_information", identifier_present=True)] + BARE[2:]
    assert "company_identifiers" not in ids(build(checks))


def test_domain_hint_is_skipped_when_the_domain_was_checked():
    checks = [c("domain_verification", "pass")] + BARE[1:]
    assert "sender_email" not in ids(build(checks))


def test_screenshot_hint_only_for_scam_wording_without_an_image():
    scam = BARE[:4] + [c("scam_text_patterns", "fail")]
    assert "payment_screenshot" in ids(build(scam))
    assert "payment_screenshot" not in ids(build(scam, had_image=True))
    assert "payment_screenshot" not in ids(build(BARE))


def test_api_returns_hints_for_bare_text(api_client):
    body = api_client.post("/analyze", data={"text": "You are selected for an internship. Join Monday."}).json()
    assert "company_identifiers" in [h["id"] for h in body["evidence_hints"]]


def test_api_returns_no_hints_for_a_payment_demand(api_client):
    body = api_client.post("/analyze", data={"text": "Pay a security deposit of Rs 2000 to confirm your seat."}).json()
    assert body["evidence_hints"] == []
