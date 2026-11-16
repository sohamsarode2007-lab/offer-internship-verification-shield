"""
Scam-chat wording (regular-expression rules only; no ML)

Recognises the wording of the scams that spread through WhatsApp and Telegram rather than
through a formal offer letter. Two tiers, each a fixed list of patterns:

  STRONG (the arrangement itself is the scam pattern)
    paid_tasks        "like/rate/review videos or products and earn", "Rs 500 per task",
                      "prepaid/combination/merchant tasks"
    pay_to_withdraw   "recharge/deposit/pay ... to withdraw/unlock your earnings",
                      "withdrawal fee/tax", "tax or release charges before salary"
  MODERATE (common in scams, but occasionally used by genuine recruiters)
    chat_only         recruiter or "HR" reached only through WhatsApp/Telegram, t.me, wa.me
    easy_money        "selected without interview", "no interview required",
                      "earn Rs 5,000 daily"

A pattern is ignored when a negation ("never", "not", "do not", ...) precedes it in the same
sentence, using the same negation rules as payment_detection ("We never ask you to join a
Telegram group" is not a hit).

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
    ]),
    "pay_to_withdraw": (True, [
        r"\b(?:recharge|top[-\s]?up|deposit|pay)\b.{0,60}\b(?:to|before)\s+(?:withdraw|unlock|release|activate|receive)\b.{0,30}\b(?:earnings?|salary|commission|balance|account|income|amount|payment)\b",
        r"\bwithdraw(?:al)?\b.{0,60}\b(?:fee|tax|charges?|recharge|deposit)\b",
        r"\b(?:tax|gst|clearance|release)\s+(?:fee|charges?)\b.{0,60}\b(?:salary|earnings|withdraw)",
    ]),
    "chat_only": (False, [
        r"\b(?:whats\s*app|telegram)\b.{0,60}\b(?:hr|recruiter|manager|team|group|channel|number|chat|join)\b",
        r"\b(?:contact|message|text|chat|msg|join|ping)\b.{0,40}\b(?:whats\s*app|telegram)\b",
        r"\b(?:t\.me|wa\.me)/|chat\.whatsapp\.com",
    ]),
    "easy_money": (False, [
        r"\b(?:selected|shortlisted|hired|approved)\b.{0,30}\bwithout\s+(?:any\s+)?(?:an?\s+)?interview\b",
        r"\bno\s+interview\s+(?:required|needed|necessary|process)\b",
        r"\bearn\b.{0,20}" + _AMOUNT + r".{0,20}\b(?:daily|per\s+day|a\s+day|per\s+week|weekly)\b",
    ]),
}
_COMPILED = {name: (strong, [re.compile(p, re.IGNORECASE | re.DOTALL) for p in patterns])
             for name, (strong, patterns) in _FAMILIES.items()}

LABELS = {
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
                if not _is_negated(raw_text, start, m.start()):
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
