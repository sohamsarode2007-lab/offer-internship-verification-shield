"""A message the person can send to the employer to confirm an offer (rule-based, nothing is sent or stored).

Rules:
  - Fixed wording; the only value taken from the offer is the company name, which the response already returns
    for display. It is never stored or logged.
  - The person sends it to contact details they find themselves (the company's own website, typed into the browser),
    never to anything named in the offer. This tool does not look up or claim any "verified" contact.
  - Not offered when a payment demand was found: the verdict is already settled and writing to the sender is not advised.
"""
from typing import Any, Dict, List, Optional

from app.utils.field_utils import get_field_value

PLACEHOLDER_COMPANY = "your company"


def build_employer_message(facts: Dict[str, Any], checks: List[dict]) -> Optional[Dict[str, Any]]:
    if any(c.get("check_name") == "payment_detection" and c.get("status") == "fail" for c in checks):
        return None
    company = (get_field_value(facts, "company_name", "company_name_legacy") or "").strip()
    # A long or odd extraction is more likely a sentence fragment than a name: leave a blank to fill in.
    if not company or len(company) > 80 or "\n" in company:
        company = PLACEHOLDER_COMPANY
    body = (
        f"Hello,\n\n"
        f"I have received an offer that names {company}. I would like to confirm it before I accept or share anything.\n\n"
        f"Could you please confirm:\n"
        f"1. That this role exists and the offer was issued by your HR team.\n"
        f"2. That [sender's name and email address as shown on the offer] is a person who works for you.\n"
        f"3. That no fee or deposit is needed at any stage.\n\n"
        f"I have not paid anything or sent any documents.\n\n"
        f"Thank you,\n[Your name]"
    )
    return {
        "title": "Ask the company to confirm this offer",
        "why": "The surest check is to ask the employer directly. This is a message you can copy and send; "
               "this tool does not send it and does not know the company's real contact details.",
        "steps": [
            "Find the company's own website yourself: search for it or type the address you already know. "
            "Do not use any link, phone number or email address from the offer.",
            "Use the careers, HR or contact details on that website.",
            "Fill in the two bracketed blanks, then send the message.",
            "Wait for a reply from the company's own address. Do not pay or share documents until you have it.",
        ],
        "subject": "Please confirm an offer made in your company's name",
        "body": body,
        "caution": "A reply from the same address as the offer proves nothing. Only a reply from the company's own "
                   "website contact counts.",
    }
