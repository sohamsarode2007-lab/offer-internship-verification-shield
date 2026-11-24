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
        reg_check.update(registry_checked=True, verification_source="mca_registry", verified_identifier_type="CIN",
                         registry_company_name="Quillmere Software Private Limited")
    return [
        {"check_name": "domain_verification", "status": domain, "domain": "quillmere.example"},
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


# ---- Hinglish / Hindi wording (narrow rules; await native-speaker review) ----
@pytest.mark.parametrize("text, family", [
    ("Ghar baithe videos like karke roz 500 rupaye kamaye.", "paid_tasks"),
    ("घर बैठे वीडियो लाइक करके रोज़ 500 रुपये कमाएं।", "paid_tasks"),
    ("Paise jama karo aur withdraw karo apna commission.", "pay_to_withdraw"),
    ("Pehle recharge karo tabhi paisa nikal paoge.", "pay_to_withdraw"),
    ("Telegram par sampark karein.", "chat_only"),
    ("टेलीग्राम पर संपर्क करें।", "chat_only"),
    ("Bina interview ke job milegi.", "easy_money"),
    ("बिना इंटरव्यू नौकरी पाएं।", "easy_money"),
    ("Interview ki zarurat nahi hai.", "easy_money"),
])
def test_hinglish_rules_trigger(text, family):
    result = scan(text)
    assert result["status"] == "fail" and family in result["families"]


@pytest.mark.parametrize("text", [
    "Hum bina interview ke kisi ko select nahi karte.",
    "हम बिना इंटरव्यू किसी का चयन नहीं करते।",
    "You will learn how customers deposit and withdraw cash at the branch counter.",
    "Complete onboarding to unlock your laptop and deposit your documents with HR.",
    "Aap apna ID card HR se nikal sakte hain; documents deposit karne ke baad unlock hoga.",
    "Is job ke liye koi fee nahi lagti. Interview ke baad offer milega.",
])
def test_hinglish_rules_do_not_trigger_on_ordinary_or_negated_wording(text):
    assert scan(text)["status"] == "not_applicable"


def test_danda_ends_a_sentence_so_a_later_negation_does_not_leak_back():
    text = "बिना इंटरव्यू नौकरी पाएं। हम कभी पैसे नहीं मांगते।"
    assert "easy_money" in scan(text)["families"]


# ---- fake cheque, re-shipping, gift card, crypto, OTP and refund-request wording ----
@pytest.mark.parametrize("text, family", [
    ("We will mail you a cheque. Deposit the cheque and then transfer the remaining balance to our vendor.", "fake_cheque"),
    ("You will receive packages at your home and reship them to our clients.", "reshipping"),
    ("This is a parcel forwarding job from home.", "reshipping"),
    ("Buy Google Play cards worth Rs 5000 and share the pin.", "gift_card"),
    ("Scratch the card and send the gift card code on Telegram.", "gift_card"),
    ("Buy USDT and send it to the wallet address we give you.", "crypto"),
    ("To activate your account please share the OTP you receive.", "otp_sharing"),
    ("Please send us the CVV to confirm.", "otp_sharing"),
    ("We accidentally paid you more than the stipend; please send back the excess.", "refund_request"),
    ("Please return the overpayment by UPI.", "refund_request"),
])
def test_advance_fee_style_wording_triggers_strong(text, family):
    result = scan(text)
    assert result["status"] == "fail" and family in result["families"] and result["tier"] == "strong"


@pytest.mark.parametrize("text", [
    "We will send you an Amazon gift card as a joining bonus.",
    "Never share your OTP with anyone, including us.",
    "Please do not share your OTP or CVV with anyone.",
    "You will receive an OTP to verify your email.",
    "We do not accept cheques.",
    "We will never ask you to buy gift cards.",
    "The role involves building a crypto wallet app; deposit your documents with HR.",
    "Your laptop will be shipped to your home; return it when the internship ends.",
    "Return the signed offer letter by Friday.",
])
def test_ordinary_and_negated_wording_does_not_trigger(text):
    assert scan(text)["status"] == "not_applicable"
