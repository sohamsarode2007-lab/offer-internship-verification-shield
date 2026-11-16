"""Scam-chat wording rules. Expected scores are derived by hand from the risk_scoring docstring."""
import pytest

from app.services import risk_scoring as rs
from app.services.institution_dashboard import classify_scam
from app.services.scam_text import detect_scam_text


def scan(text):
    return detect_scam_text({"raw_text": text})


@pytest.mark.parametrize("text, family", [
    ("Like 5 videos every day and earn money from home.", "paid_tasks"),
    ("You will earn Rs 500 per task.", "paid_tasks"),
    ("Complete the prepaid tasks to unlock the next level.", "paid_tasks"),
    ("Recharge your account to withdraw your earnings.", "pay_to_withdraw"),
    ("A withdrawal fee of Rs 2,000 must be paid first.", "pay_to_withdraw"),
    ("Contact our HR on WhatsApp for the joining details.", "chat_only"),
    ("Join the group at t.me/hiringteam now.", "chat_only"),
    ("You are selected without interview.", "easy_money"),
    ("No interview required, start today.", "easy_money"),
    ("Earn Rs 5,000 daily from your phone.", "easy_money"),
])
def test_each_family_triggers(text, family):
    result = scan(text)
    assert result["status"] == "fail" and family in result["families"]


@pytest.mark.parametrize("text", [
    "We will never ask you to join a Telegram group.",
    "HR does not contact candidates on WhatsApp.",
    "There is no withdrawal fee on the provident fund.",
    "Your daily tasks include writing reports and attending stand-ups.",
    "Please reply to hr@brightwave.example with your documents.",
    "Interview rounds: aptitude test, technical interview, HR interview.",
    "",
])
def test_ordinary_wording_does_not_trigger(text):
    result = scan(text)
    assert result["status"] == "not_applicable" and result["families"] == []


def test_tier_is_strong_when_any_strong_family_matches():
    assert scan("Contact HR on Telegram. Rate products and earn commission.")["tier"] == "strong"
    assert scan("Contact HR on Telegram.")["tier"] == "moderate"


def test_details_never_echo_offer_text():
    text = "Contact Priya Sharma on WhatsApp 9876543210 to rate products and earn commission."
    details = scan(text)["details"]
    assert "Priya" not in details and "9876543210" not in details


def checks(scam=None, *, domain="pass", reg="insufficient_information", present=True, registry=False):
    reg_check = {"check_name": "gstin_verification", "status": "pass" if registry else reg,
                 "identifier_present": present}
    if registry:
        reg_check.update(registry_checked=True, verification_source="mca_registry", verified_identifier_type="CIN")
    return [
        {"check_name": "domain_verification", "status": domain},
        reg_check,
        {"check_name": "payment_detection", "status": "pass"},
        {"check_name": "scam_text_patterns", **(scam or {"status": "not_applicable", "families": [], "tier": None})},
    ]


STRONG = {"status": "fail", "tier": "strong", "families": ["paid_tasks"], "details": "x"}
MODERATE = {"status": "fail", "tier": "moderate", "families": ["chat_only"], "details": "x"}
BOTH = {"status": "fail", "tier": "strong", "families": ["paid_tasks", "chat_only"], "details": "x"}


def test_verified_company_without_scam_wording_is_legitimate():
    # no points; offsets floor at 0; registry match is an external signal -> 0, likely legitimate
    result = rs.calculate_risk_score(checks(registry=True))
    assert result["overall_risk_score"] == 0 and result["risk_band"] == "likely legitimate"


def test_strong_wording_blocks_likely_legitimate():
    # +30 -10 (domain) -10 (registry) = 10 <= 30, but the strong pattern raises it to 31
    result = rs.calculate_risk_score(checks(STRONG, registry=True))
    assert result["overall_risk_score"] == 31 and result["risk_band"] == "insufficient evidence, verify manually"
    assert any("task-scam" in r["text"] for r in result["reasons"])


def test_moderate_wording_adds_points_but_does_not_block_legitimate():
    # +15 -10 (domain) -5 (registry, only 5 left) = 0 -> still likely legitimate
    result = rs.calculate_risk_score(checks(MODERATE, registry=True))
    assert result["overall_risk_score"] == 0 and result["risk_band"] == "likely legitimate"


def test_strong_wording_with_no_identifiers_is_high_risk():
    # +30 strong +20 no registration number +20 no domain and no registration = 70
    result = rs.calculate_risk_score(checks(STRONG, domain="not_applicable", present=False))
    assert result["overall_risk_score"] == 70 and result["risk_band"] == "high risk"


def test_both_tiers_add_extra_ten():
    result = rs.calculate_risk_score(checks(BOTH, domain="not_applicable", present=False))
    assert result["overall_risk_score"] == 80


def test_strong_wording_alone_is_not_high_risk_for_an_otherwise_passing_letter():
    # +30 +10 (unverified registration) -10 (domain) = 30 -> raised to 31, not 61+
    result = rs.calculate_risk_score(checks(STRONG))
    assert result["overall_risk_score"] == 31


def test_category_is_task_or_chat_scam_unless_payment_rule_applies():
    scam = {"check_name": "scam_text_patterns", **STRONG}
    assert classify_scam([scam], "") == "task_or_chat_scam"
    payment = {"check_name": "payment_detection", "status": "fail", "demands": ["security deposit"]}
    assert classify_scam([payment, scam], "") == "security_deposit"


def test_analyze_flags_task_scam_text(api_client):
    text = "Work from home. Rate products and earn Rs 500 per task. Contact our HR on Telegram."
    body = api_client.post("/analyze", data={"text": text}).json()
    check = next(c for c in body["checks"] if c["check_name"] == "scam_text_patterns")
    assert check["status"] == "fail"
    assert body["risk_band"] == "high risk"
    assert text not in str(body)
