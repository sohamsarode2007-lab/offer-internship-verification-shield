"""
Requests for bank details or identity documents (regular-expression rules only; no ML)

Scammers collect personal data before any real hiring step. Genuine employers also ask for it, but
normally AFTER an offer is accepted, so this is a moderate warning, never a verdict.

  credentials a request to send/share a password, PIN, OTP, CVV or net-banking login. No employer ever needs
              these, so joining/onboarding wording never cancels this tier                 -> +40
  bank        a request to send/share/upload bank account details, account number, IFSC, cancelled cheque,
              debit/credit card details or net-banking login                       -> +20
  documents   a request to send/share/upload an Aadhaar or PAN copy, passport, voter ID, driving licence,
              passport-size photo, marksheets or experience/educational certificates -> +10

The points are not added together: credentials win, then bank (+20), then documents. The check never forces
high risk by itself (a payment demand still does that, separately).

A request must contain an asking verb (send, share, submit, upload, provide, email, forward, give,
whatsapp, bhejiye ...) within a short distance of the item. A pattern is ignored when a negation precedes it in
the same sentence ("We never ask for bank details"), and when the same sentence places the request after joining
("Please bring your original documents on the day of joining"; "submit after you join"). Hindi/Hinglish rules
are deliberately narrow and still await review by a native speaker; see docs/JUDGMENT_CALLS.md.

Result: status 'fail' when any pattern matches, otherwise 'not_applicable' (absence says nothing about whether
an offer is genuine). 'tier' is 'bank' or 'documents'; 'families' lists the rule names that matched.

Privacy: details name the rule families only. No text from the offer is echoed back.
"""
import re
from typing import Any, Dict, List

from app.services.payment_detection import _is_negated, _sentence_of, sentence_spans
from app.utils.field_utils import get_field_value

CHECK_NAME = "personal_data_request"

_ASK = (r"(?:send|share|submit|upload|provide|email|e-mail|mail|forward|give|whatsapp|attach|scan\s+and\s+send|"
        r"fill\s+in|enter|need|require|required|requires|reply\s+with)")
_BANK_ITEM = (r"(?:bank\s+(?:account\s+)?(?:details|number|statement|passbook|login|credentials)|"
              r"account\s+(?:number|details)|ifsc|cancell?ed\s+cheque|(?:debit|credit|atm)\s+card\s*(?:details|number|photo|copy)?|"
              r"net[-\s]?banking\s+details|internet\s+banking\s+details)")
_CRED_ASK = r"(?:send|share|tell|give|provide|forward|whatsapp|text|read\s+out|submit|email|e-mail|mail)"
_CRED_ITEM = (r"(?:(?:net|internet)[-\s]?banking\s+(?:login|password|id|credentials|pin)|passwords?|passcodes?|"
              r"(?:atm|upi|debit|credit|card|secret|m|transaction)[-\s]?pin|pin\s+number|pin(?!\s*code)\b|"
              r"otps?|one[-\s]time\s+(?:password|passcode|code)|cvv|cvc|card\s+verification)")
_DOC_ITEM = (r"(?:aadh?aa?r(?:\s+card)?|pan\s+card|copy\s+of\s+(?:your\s+)?pan|passport(?:\s+copy)?|voter\s+id|"
             r"driving\s+licen[cs]e|passport[-\s]size\s+photos?|(?:recent\s+)?photograph|marksheets?|"
             r"(?:experience|educational|academic|10th|12th)\s+(?:certificates?|documents?)|original\s+documents)")

_FAMILIES = {
    "credentials": [
        rf"\b{_CRED_ASK}\b.{{0,50}}\b{_CRED_ITEM}",
        rf"\b{_CRED_ITEM}\b.{{0,40}}\b(?:is|are)\s+(?:needed|required|mandatory)\b",
    ],
    "bank": [
        rf"\b{_ASK}\b.{{0,50}}\b{_BANK_ITEM}\b",
        rf"\b{_BANK_ITEM}\b.{{0,40}}\b(?:is|are)\s+(?:needed|required|mandatory)\b",
        rf"\b{_BANK_ITEM}\b.{{0,40}}\b(?:bhej\w*|share\s+kar\w*|send\s+kar\w*|dena|do)\b",
    ],
    "documents": [
        rf"\b{_ASK}\b.{{0,50}}\b{_DOC_ITEM}\b",
        rf"\b{_DOC_ITEM}\b.{{0,40}}\b(?:is|are)\s+(?:needed|required|mandatory)\b",
        rf"\b{_DOC_ITEM}\b.{{0,40}}\b(?:bhej\w*|share\s+kar\w*|send\s+kar\w*|dena|do)\b",
    ],
}
_COMPILED = {name: [re.compile(p, re.IGNORECASE | re.DOTALL) for p in patterns] for name, patterns in _FAMILIES.items()}

# The request is placed after joining/onboarding: how genuine employers usually phrase it.
_AFTER_JOINING_RE = re.compile(
    r"\b(?:after|upon|once|on|at)\s+(?:you\s+)?(?:the\s+)?(?:join(?:ed|ing)?|joining|day\s+of\s+joining|first\s+day|"
    r"onboarding|your\s+first\s+day|date\s+of\s+joining|time\s+of\s+joining)\b"
    r"|\bduring\s+(?:the\s+)?onboarding\b|\bon\s+the\s+day\s+of\s+joining\b|\bcarry\b.{0,30}\boriginals?\b",
    re.IGNORECASE,
)
_POST_NEGATION_RE = re.compile(r"\b(?:nahi|nahin|nhi|mat)\b|नहीं|मत", re.IGNORECASE)
_POST_NEGATION_WINDOW = 40

LABELS = {
    "credentials": "a request for a password, PIN, OTP or card security code",
    "bank": "a request for bank account or card details",
    "documents": "a request for identity documents, photographs or certificates",
}


def detect_personal_data_request(facts: Dict[str, Any]) -> Dict[str, Any]:
    raw_text = get_field_value(facts, "raw_text") or ""
    if not raw_text:
        return _result([], "No offer text available to scan.")
    spans = sentence_spans(raw_text)
    families: List[str] = []
    for name, patterns in _COMPILED.items():
        for pattern in patterns:
            for m in pattern.finditer(raw_text):
                start, end = _sentence_of(spans, m.start())
                sentence = raw_text[start:end]
                tail = raw_text[m.end():min(end, m.end() + _POST_NEGATION_WINDOW)]
                # Secrets are never "after joining": only ordinary documents and account details get that exception.
                after_joining = name != "credentials" and _AFTER_JOINING_RE.search(sentence)
                if _is_negated(raw_text, start, m.start()) or _POST_NEGATION_RE.search(tail) or after_joining:
                    continue
                families.append(name)
                break
            if name in families:
                break
    return _result(families, "")


def _result(families: List[str], empty_details: str) -> Dict[str, Any]:
    if not families:
        return {"check_name": CHECK_NAME, "status": "not_applicable", "score": 0.0, "families": [], "tier": None,
                "details": empty_details or "No request for bank details or identity documents found. "
                                            "This does not show the offer is genuine."}
    tier = "credentials" if "credentials" in families else "bank" if "bank" in families else "documents"
    return {
        "check_name": CHECK_NAME, "status": "fail", "score": 100.0, "families": families, "tier": tier,
        "details": "The text asks for " + " and ".join(LABELS[f] for f in families)
                   + (". No genuine employer needs a password, PIN or OTP: do not share them." if tier == "credentials"
                      else ". Genuine employers ask for these after an offer is accepted, not before; check who is asking first."),
    }
