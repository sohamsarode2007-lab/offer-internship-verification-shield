"""Safety playbook: matched steps, fixed contacts, nothing from the offer text."""
from app.services.safety_playbook import HELPLINE, PORTAL_URL, build_safety_actions

PAY = {"check_name": "payment_detection", "status": "fail"}
OK_PAY = {"check_name": "payment_detection", "status": "pass"}


def scam(*families):
    return {"check_name": "scam_text_patterns", "status": "fail", "families": list(families)}


def ids(actions):
    return [a["id"] for a in actions]


def test_payment_demand_gets_do_not_pay_and_report():
    actions = build_safety_actions([PAY], "pay now", "high risk")
    assert ids(actions) == ["payment", "report"]
    report = actions[-1]
    assert report["helpline"] == HELPLINE == "1930" and report["url"] == PORTAL_URL
    assert actions[0]["urgent"] is True


def test_family_specific_steps():
    actions = build_safety_actions([OK_PAY, scam("fake_cheque", "otp_sharing", "crypto")], "x", "medium risk")
    assert ids(actions) == ["cheque_or_shipping", "otp", "gift_or_crypto", "report"]
    assert actions[-1]["urgent"] is False


def test_suspicious_link_adds_link_advice():
    actions = build_safety_actions([OK_PAY], "Apply at http://bit.ly/abc123", "medium risk")
    assert ids(actions) == ["links"]


def test_clean_offer_gets_no_actions():
    assert build_safety_actions([OK_PAY, {"check_name": "scam_text_patterns", "status": "not_applicable"}],
                                "Please join on Monday.", "likely legitimate") == []


def test_offer_text_never_appears_in_output():
    secret = "Rahul Sharma 9876543210"
    assert secret not in str(build_safety_actions([PAY], secret, "high risk"))
