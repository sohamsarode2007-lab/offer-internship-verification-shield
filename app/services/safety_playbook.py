"""
Safety playbook: what to do next, matched to what was found (rule-based, deterministic, no stored data).

Contact points are fixed constants: the National Cyber Crime Helpline 1930 and the National Cyber Crime
Reporting Portal (cybercrime.gov.in). Nothing here is built from offer text, and it never claims an
action was taken for the person. Steps are advice only, not legal advice.
"""
from typing import Any, Dict, List

from app.services import url_evidence

HELPLINE = "1930"
PORTAL_URL = "https://cybercrime.gov.in/"

_REPORT = {
    "label": "Report it",
    "steps": [
        "If money has already left your account, contact your bank or payment app immediately and ask what hold or reversal options are available.",
        "Then call 1930 straight away (the sooner, the better the chance of a hold).",
        "Then file a complaint on the National Cyber Crime Reporting Portal (cybercrime.gov.in).",
        "Keep screenshots of the offer, the sender's address, payment details and any receipts. Do not delete the chat.",
    ],
}


def _action(action_id: str, title: str, steps: List[str], urgent: bool = False) -> Dict[str, Any]:
    return {"id": action_id, "title": title, "steps": steps, "urgent": urgent}


def _check(checks: List[dict], name: str) -> dict:
    return next((c for c in checks if c.get("check_name") == name), {})


def build_safety_actions(checks: List[dict], raw_text: str, risk_band: str, link_threat: bool = False) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = []
    payment = _check(checks, "payment_detection").get("status") == "fail"
    scam = _check(checks, "scam_text_patterns")
    families = set(scam.get("families") or []) if scam.get("status") == "fail" else set()

    if payment:
        actions.append(_action("payment", "Do not pay", [
            "Do not pay any fee, deposit, kit or 'security' amount to get a job or internship.",
            "A legitimate employer should not require a fee, deposit, kit charge or security amount as a condition of getting the job or internship.",
        ], urgent=True))
    if "fake_cheque" in families or "reshipping" in families:
        actions.append(_action("cheque_or_shipping", "Do not deposit cheques or forward parcels", [
            "Do not deposit a cheque or transfer 'extra' money onward; the cheque can bounce after you have sent real money.",
            "Do not receive or re-ship packages for an employer you have not verified.",
        ], urgent=True))
    if "otp_sharing" in families:
        actions.append(_action("otp", "Never share OTPs or passwords", [
            "No recruiter needs your OTP, UPI PIN, card details or net-banking password.",
            "If you already shared one, call your bank now and change the password.",
        ], urgent=True))
    if "gift_card" in families or "crypto" in families:
        actions.append(_action("gift_or_crypto", "Do not buy gift cards or crypto for an employer", [
            "Payment by gift card or cryptocurrency is a common scam signal and is very hard to reverse.",
        ], urgent=True))
    if link_threat or url_evidence.url_flags(raw_text):
        actions.append(_action("links", "Be careful with the links", [
            "Do not click or log in through links in this offer. Type the company's website address yourself.",
            "Never enter your Aadhaar, PAN or bank details on a page you reached from this message.",
        ]))
    if payment or families or risk_band == "high risk":
        actions.append({"id": "report", "title": "If you have lost money or shared details",
                        "steps": _REPORT["steps"], "urgent": payment, "helpline": HELPLINE, "url": PORTAL_URL})
    return actions
