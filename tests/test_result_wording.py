"""Student-facing wording on the result screen (plain 'Why' rows, next steps, report offer)."""
import re
import uuid


from app.services import gstin_verification as gv, risk_scoring as rs

ENGINE_WORDS = re.compile(r"offset|score floor|'likely legitimate'|'high risk'|rule_based|MCA registry pass", re.I)


def _score(checks):
    return rs.calculate_risk_score(checks)


def test_reasons_carry_plain_text_and_impact():
    result = _score([
        {"check_name": "payment_detection", "status": "fail", "demands": ["security deposit"], "urgency": ["within 24 hours"]},
        {"check_name": "domain_verification", "status": "fail", "details": "Contact address uses the free mailbox provider 'gmail.com'."},
        {"check_name": "gstin_verification", "status": "insufficient_information", "identifier_present": False},
    ])
    reasons = {r["text"]: r["impact"] for r in result["reasons"]}
    assert reasons["The letter asks you to pay money before you join"] == "+65"
    assert reasons['It pressures you to pay quickly ("within 24 hours")'] == "+20"
    assert reasons["The contact email is a free personal mailbox (like Gmail), not a company address"] == "+30"
    assert all(not ENGINE_WORDS.search(r["text"]) for r in result["reasons"])


def test_raised_to_31_reads_as_plain_sentence():
    result = _score([
        {"check_name": "domain_verification", "status": "pass"},
        {"check_name": "gstin_verification", "status": "insufficient_information", "identifier_present": False},
        {"check_name": "payment_detection", "status": "pass"},
    ])
    assert result["overall_risk_score"] == 31
    texts = [r["text"] for r in result["reasons"]]
    assert "We couldn't verify this company's registration, so we can't call it legitimate yet." in texts
    assert "−10" in [r["impact"] for r in result["reasons"]]          # true minus sign, no 'offset'


def test_likely_legitimate_lists_what_was_verified():
    result = _score([
        {"check_name": "domain_verification", "status": "pass", "domain": "quillmere.example"},
        {"check_name": "gstin_verification", "status": "pass", "identifier_present": True, "registry_checked": True,
         "verification_source": "mca_registry", "verified_identifier_type": "CIN",
         "registry_company_name": "Quillmere Software Private Limited"},
        {"check_name": "payment_detection", "status": "pass"},
    ])
    assert result["risk_band"] == "likely legitimate"
    texts = [r["text"] for r in result["reasons"]]
    assert texts == ["The company's email domain exists and can receive email",
                     "The company is registered and active: Quillmere Software Private Limited",
                     "No payment was requested"]
    assert all(not ENGINE_WORDS.search(t) for t in texts)


def test_location_note_grammar():
    note = gv._gstin_cin_state_note("07AAFCE4321L1ZO", "U74999DL2016PTC298345")
    assert "these locations are consistent" in note
    assert "these locations consistent" not in note


def test_high_risk_next_steps_name_1930_and_cybercrime_portal(api_client):
    body = api_client.post("/analyze", data={"text": "Selected. Pay registration fee Rs 499 to confirm."}).json()
    assert body["risk_band"] == "high risk"
    assert ("If you've already paid, call the National Cyber Crime Helpline 1930 immediately and report at "
            "cybercrime.gov.in.") in body["next_steps"]
    assert not ENGINE_WORDS.search(body["complaint_summary"])


def test_who_sent_it_hint_when_not_an_eml(api_client):
    body = api_client.post("/analyze", data={"text": "A remote internship offer."}).json()
    auth = next(c for c in body["checks"] if c["check_name"] == "sender_authentication")
    assert auth["status"] == "not_applicable"
    assert auth["details"] == "Upload the original email (.eml) to check who sent it."


def test_no_report_offer_for_likely_legitimate(demo_client, monkeypatch, synthetic_registry_db):
    from conftest import DEMO_DIR
    monkeypatch.setenv("INDICATOR_PEPPER", "wording-test-" + uuid.uuid4().hex)
    legit = demo_client.post("/analyze", data={"text": (DEMO_DIR / "legit_emberlake.txt").read_text(encoding="utf-8")}).json()
    assert legit["risk_band"] == "likely legitimate"
    assert legit["report_token"] is None and legit["reportable_indicators"] == []
    manual = demo_client.post("/analyze", data={
        "text": (DEMO_DIR / "legit_brightpath_young_startup.txt").read_text(encoding="utf-8")}).json()
    assert manual["risk_band"] == "insufficient evidence, verify manually"
    assert manual["report_token"]
