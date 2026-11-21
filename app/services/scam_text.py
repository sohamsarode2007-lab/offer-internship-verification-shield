"""
Scam-chat wording (regular-expression rules only; no ML)

Recognises the wording of the scams that spread through WhatsApp and Telegram rather than
through a formal offer letter. Two tiers, each a fixed list of patterns:

  STRONG (the arrangement itself is the scam pattern)
    paid_tasks        "like/rate/review videos or products and earn", "Rs 500 per task",
                      "prepaid/combination/merchant tasks", limited Hinglish/Hindi equivalents
    pay_to_withdraw   "recharge/deposit/pay ... to withdraw/unlock your earnings",
                      "withdrawal fee/tax", "tax or release charges before salary", limited Hinglish/Hindi equivalents
    fake_cheque       a cheque/draft to deposit, then send back the "balance/excess"
    reshipping        receive packages at home and re-ship/forward them
    gift_card         buy gift cards, or send gift-card codes/PINs
    crypto            buy/send crypto to a wallet address as part of the "job"
    otp_sharing       share/tell/give an OTP, CVV or UPI/ATM PIN
    refund_request    "we paid you too much, send the extra back"
  MODERATE (common in scams, but occasionally used by genuine recruiters)
    chat_only         recruiter or "HR" reached only through WhatsApp/Telegram, t.me, wa.me
    easy_money        "selected without interview", "no interview required",
                      "earn Rs 5,000 daily"

A pattern is ignored when a negation ("never", "not", "do not", ...) precedes it in the same
sentence, using the same negation rules as payment_detection ("We never ask you to join a
Telegram group" is not a hit). Hindi/Hinglish negation usually FOLLOWS the phrase ("... select nahi
karte"), so a Hindi negation word (nahi, nahin, nhi, mat, नहीं, मत) shortly after the match in the same
sentence also cancels it. Hindi rules are deliberately narrow (money/withdraw context required) and still
await review by a native speaker; see docs/JUDGMENT_CALLS.md.

Result: status 'fail' when any pattern matches, otherwise 'not_applicable' (absence of
these phrases says nothing about whether an offer is genuine). 'tier' is 'strong' when a
strong pattern matched, else 'moderate'. 'families' lists the rule names that matched.

Privacy: details name the rule families only. No text from the offer is echoed back.
"""
import re
from typing import Any, Dict, List

from app.services.payment_detection import _is_negated, _sentence_of, sentence_spans
from app.utils.field_utils import get_field_value

CHECK_NAME = "scam_text_patterns"

_AMOUNT = r"(?:rs\.?|inr|₹)\s*[\d,]+"

_FAMILIES = {
    "paid_tasks": (True, [
        r"\b(?:like|subscribe(?:\s+to)?|follow|rate|review|watch)\b.{0,40}\b(?:videos?|reels?|channels?|posts?|products?|hotels?|apps?|restaurants?)\b.{0,80}\b(?:earn|income|commission|paid)\b",
        r"\b(?:earn|get\s+paid|receive)\b.{0,30}" + _AMOUNT + r".{0,25}\b(?:per|for\s+each|every)\s+(?:task|video|like|review|order|click|rating|app)\b",
        r"\b(?:prepaid|combination|merchant|premium)\s+tasks?\b",
        r"\bcomplete\s+(?:\d+\s+)?(?:simple|easy|online)\s+tasks?\b.{0,30}\b(?:daily|per\s+day|and\s+earn)\b",
        r"\b(?:videos?|reels?|posts?|products?|hotels?|apps?)\b.{0,40}\b(?:like|rate|review)\s+kar\w*.{0,80}\b(?:earn|income|commission|paid|kamai|kama\w*)\b",
        r"(?:वीडियो|रील|प्रोडक्ट|होटल|ऐप).{0,40}(?:लाइक|रेटिंग|रिव्यू).{0,80}(?:कमा|कमाई|कमीशन)",
    ]),
    "pay_to_withdraw": (True, [
        r"\b(?:recharge|top[-\s]?up|deposit|pay)\b.{0,60}\b(?:to|before)\s+(?:withdraw|unlock|release|activate|receive)\b.{0,30}\b(?:earnings?|salary|commission|balance|account|income|amount|payment)\b",
        r"\bwithdraw(?:al)?\b.{0,60}\b(?:fee|tax|charges?|recharge|deposit)\b",
        r"\b(?:tax|gst|clearance|release)\s+(?:fee|charges?)\b.{0,60}\b(?:salary|earnings|withdraw)",
        r"\b(?:recharge|top[-\s]?up|paise?\s+(?:jama|bharo))\b.{0,60}\b(?:withdraw|nikal\w*)\b",
        r"\b(?:withdraw|nikal\w*)\b.{0,60}\b(?:recharge|top[-\s]?up|paise?\s+(?:jama|bharo))\b",
    ]),
    "fake_cheque": (True, [
        r"\b(?:cheque|check|cashier'?s\s+check|demand\s+draft|money\s+order)\b.{0,80}\b(?:deposit|cash)\b.{0,100}\b(?:send|transfer|wire|return|forward)\b.{0,60}\b(?:balance|remaining|rest|excess|difference|extra)\b",
    ]),
    "reshipping": (True, [
        r"\b(?:receive|accept)\b.{0,40}\b(?:packages?|parcels?|shipments?)\b.{0,60}\b(?:re-?ship|forward|repack|send\s+(?:them|it)\s+on)\w*",
        r"\b(?:re-?shipping|package\s+forwarding|parcel\s+forwarding)\s+(?:job|agent|work|position|role)\b",
    ]),
    "gift_card": (True, [
        r"\b(?:buy|purchase)\b.{0,40}\b(?:gift\s*cards?|google\s*play\s*cards?|itunes\s*cards?|steam\s*cards?|amazon\s*(?:pay\s*)?cards?)\b",
        r"\b(?:send|share|read\s+out|scratch)\b.{0,30}\bgift\s*cards?\b.{0,30}\b(?:codes?|pins?|numbers?|photos?)\b",
    ]),
    "crypto": (True, [
        r"\b(?:buy|purchase|send|transfer|deposit)\b.{0,60}\b(?:bitcoin|btc|usdt|ethereum|crypto(?:currency)?)\b.{0,60}\b(?:wallet|address)\b",
    ]),
    "otp_sharing": (True, [
        r"\b(?:share|tell|give|forward|read\s+out)\b.{0,30}\b(?:otp|one[-\s]?time\s+(?:password|pin|code)|cvv|upi\s+pin|atm\s+pin)\b",
        r"\bsend\s+(?:us|me)\b.{0,25}\b(?:otp|one[-\s]?time\s+(?:password|pin|code)|cvv)\b",
    ]),
    "refund_request": (True, [
        r"\b(?:accidentally|mistakenly|by\s+mistake)\b.{0,40}\b(?:sent|paid|transferred|credited)\b.{0,40}\b(?:more|excess|extra)\b.{0,100}\b(?:return|refund|send\s+back|transfer\s+back)\b",
        r"\b(?:return|send\s+back|transfer\s+back|refund)\b.{0,30}\b(?:the\s+)?(?:excess|extra|overpaid|overpayment)\b",
    ]),
    "chat_only": (False, [
        r"\b(?:whats\s*app|telegram)\b.{0,60}\b(?:hr|recruiter|manager|team|group|channel|number|chat|join)\b",
        r"\b(?:contact|message|text|chat|msg|join|ping)\b.{0,40}\b(?:whats\s*app|telegram)\b",
        r"\b(?:t\.me|wa\.me)/|chat\.whatsapp\.com",
        r"\b(?:whats\s*app|telegram)\b.{0,60}\b(?:sampark|baat|sandesh)\b",
        r"(?:टेलीग्राम|टेलीग्रैम|व्हाट्सएप|व्हाट्सऐप|वॉट्सऐप|वॉट्सएप).{0,60}(?:संपर्क|सम्पर्क|बात|मैसेज)",
    ]),
    "easy_money": (False, [
        r"\b(?:selected|shortlisted|hired|approved)\b.{0,30}\bwithout\s+(?:any\s+)?(?:an?\s+)?interview\b",
        r"\bno\s+interview\s+(?:required|needed|necessary|process)\b",
        r"\bearn\b.{0,20}" + _AMOUNT + r".{0,20}\b(?:daily|per\s+day|a\s+day|per\s+week|weekly)\b",
        r"\bbina\s+(?:kisi\s+)?interview\b",
        r"बिना\s+(?:किसी\s+)?इंटरव्यू",
        r"\binterview\b.{0,25}\b(?:zarurat|need)\s+(?:nahi|nahin|nhi)\b",
    ]),
}
# Hindi/Hinglish negation follows the phrase: "... select nahi karte". Only the rest of the sentence is checked.
_POST_NEGATION_RE = re.compile(r"\b(?:nahi|nahin|nhi|mat)\b|नहीं|मत", re.IGNORECASE)
_POST_NEGATION_WINDOW = 40
_COMPILED = {name: (strong, [re.compile(p, re.IGNORECASE | re.DOTALL) for p in patterns])
             for name, (strong, patterns) in _FAMILIES.items()}

LABELS = {
    "fake_cheque": "fake-cheque wording (deposit a cheque, send back the balance)",
    "reshipping": "package re-shipping wording",
    "gift_card": "gift-card wording (buy cards or send codes)",
    "crypto": "wording about buying or sending crypto to a wallet",
    "otp_sharing": "wording asking you to share an OTP, CVV or PIN",
    "refund_request": "wording asking you to send an overpayment back",
    "paid_tasks": "paid-task wording (earning for liking, rating or reviewing)",
    "pay_to_withdraw": "pay-to-withdraw wording",
    "chat_only": "recruiter reached only through WhatsApp or Telegram",
    "easy_money": "no-interview or easy-money wording",
}


def detect_scam_text(facts: Dict[str, Any]) -> Dict[str, Any]:
    """Rule-based scan of the offer text for scam-chat wording."""
    raw_text = get_field_value(facts, "raw_text") or ""
    if not raw_text:
        return _result([], "No offer text available to scan.")
    spans = sentence_spans(raw_text)
    families: List[str] = []
    for name, (_, patterns) in _COMPILED.items():
        for pattern in patterns:
            for m in pattern.finditer(raw_text):
                start, _ = _sentence_of(spans, m.start())
                _, end = _sentence_of(spans, m.start())
                tail = raw_text[m.end():min(end, m.end() + _POST_NEGATION_WINDOW)]
                if not _is_negated(raw_text, start, m.start()) and not _POST_NEGATION_RE.search(tail):
                    families.append(name)
                    break
            if name in families:
                break
    return _result(families, "")


def _result(families: List[str], empty_details: str) -> Dict[str, Any]:
    if not families:
        return {"check_name": CHECK_NAME, "status": "not_applicable", "score": 0.0, "families": [], "tier": None,
                "details": empty_details or "No known scam-chat wording found. This does not show the offer is genuine."}
    tier = "strong" if any(_COMPILED[f][0] for f in families) else "moderate"
    return {
        "check_name": CHECK_NAME, "status": "fail", "score": 100.0, "families": families, "tier": tier,
        "details": "Wording found that is typical of WhatsApp/Telegram job scams: "
                   + "; ".join(LABELS[f] for f in families) + ".",
    }
