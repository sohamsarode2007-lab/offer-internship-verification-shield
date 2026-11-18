"""
Self-checks: things the person can confirm themselves on an official site (rule-based, deterministic)

Some official look-ups sit behind a captcha that exists to stop automated queries. This tool does not
get around it and does not call those sites. Instead, when the offer quotes a number whose format is
valid, we hand the person the number and the official page so they can check it themselves.

Rules:
  - Never changes the score and is never stored or logged; the number is returned only in the response.
  - The link is a fixed constant, never built from offer text.
  - Wording is honest: we did NOT verify the number, and a match proves the number exists for that
    business name, not that this offer came from that business.
  - Nothing is returned when a payment demand was found (the verdict is already settled).
"""
import re
from typing import Any, Dict, List

from app.utils.field_utils import get_field_value

UDYAM_VERIFY_URL = "https://udyamregistration.gov.in/Udyam_Verify.aspx"
UDYAM_FORMAT_RE = re.compile(r"^UDYAM-[A-Z]{2}-[0-9]{2}-[0-9]{7}$")


def build_self_checks(facts: Dict[str, Any], checks: List[dict]) -> List[Dict[str, Any]]:
    if any(c.get("check_name") == "payment_detection" and c.get("status") == "fail" for c in checks):
        return []
    udyam = (get_field_value(facts, "udyam") or "").strip().upper()
    if not UDYAM_FORMAT_RE.match(udyam):
        return []
    return [{
        "id": "udyam",
        "title": "Check this Udyam number yourself",
        "number": udyam,
        "url": UDYAM_VERIFY_URL,
        "why": "The offer quotes a Udyam registration number. We have not verified it: the government's look-up page "
               "asks for a captcha, so only you can run it.",
        "steps": [
            "Open the Ministry of MSME Udyam verification page and enter the number exactly as shown.",
            "Type the captcha code and press Verify.",
            "Compare the business name and state with the company in the offer.",
            "If the name or state differs, or nothing is found, treat the offer as suspicious.",
        ],
        "caution": "A match only shows that the number exists for that business. A scammer can copy a real "
                   "business's number, so also check that the sender's email domain belongs to that business.",
    }]
