"""
Payment Demand Detection (regular-expression rules only; no ML / TF-IDF)

Flags an offer when it asks the candidate to pay money up front.

Rules:
  1. Scam phrases (security deposit, registration/training/processing/joining/kit/
     verification fee, refundable deposit, pay a fee, send/transfer the amount,
     pay Rs N, ...) count as a demand unless NEGATED earlier in the same sentence
     ("no", "not", "never", "without", "does not", "free of", ...). A demand verb or
     contrast word (pay/send/transfer/submit/remit/kindly/must/but/however/except/
     only/just) between the negation and the phrase cancels the negation:
       "No interview needed, just pay a security deposit"  -> demand.
  2. Sentences are split on [.!?] + whitespace and on blank lines, NOT on single
     newlines (PDF text wraps mid-sentence).
  3. UPI demand: a pay/send/transfer/deposit/remit verb up to ~120 chars before a
     UPI handle (or up to ~60 chars after it), within one sentence. Ignored when that
     span talks about stipend/salary/reimbursement (money flowing TO the candidate).
  4. Urgency is reported only when it appears within +/-250 chars of a demand.

Returns status 'fail' (demand found), 'pass' (none found) or 'not_applicable'
(no text), plus 'urgency': [matched urgency terms near a demand].

Privacy: details name the matched rule phrases and UPI payment instructions; other
surrounding offer text is not echoed back.
"""
import re
from typing import Dict, Any, List, Tuple

from app.utils.field_utils import get_field_value
from app.utils.email_domains import UPI_HANDLES

SCAM_PHRASE_PATTERNS = [
    r"security\s+deposit",
    r"refundable\s+(?:security\s+)?(?:deposit|fee|amount)",
    r"(?:registration|training|processing|joining|onboarding|verification|"
    r"document(?:\s+verification)?|background(?:\s+check)?|kit|laptop)\s+(?:fees?|charges?)",
    r"kit\s+deposit",
    r"pay\s+(?:a|an|the)?\s*(?:small\s+|nominal\s+|one[-\s]time\s+)?(?:fee|deposit|advance)",
    r"(?:send|transfer|remit|deposit)\s+(?:the|this|that)?\s*(?:money|amount|fee|deposit|advance|sum)",
    r"(?:pay|send|transfer|remit|deposit)\s+(?:rs\.?|inr|₹)\s*[\d,]+",
]
_SCAM_RE = re.compile("|".join(f"(?:{p})" for p in SCAM_PHRASE_PATTERNS), re.IGNORECASE)

_NEGATION_RE = re.compile(
    # "no" followed by "." is the abbreviation for number ("Ref No. 12"), not a negation.
    r"\b(?:no(?!\.)|not|never|without|does\s+not|do\s+not|doesn't|don't|won't|will\s+not|"
    r"need\s+not|cannot|free\s+of)\b",
    re.IGNORECASE,
)
_CANCEL_RE = re.compile(
    r"\b(?:pay|send|transfer|submit|remit|kindly|must|but|however|except|only|just)\b",
    re.IGNORECASE,
)

_UPI_RE = re.compile(
    r"\b[A-Za-z0-9._-]{2,}@(" + "|".join(sorted(UPI_HANDLES, key=len, reverse=True)) + r")\b(?!\.[A-Za-z])",
    re.IGNORECASE,
)
_PAY_VERB_RE = re.compile(
    r"\b(?:pay|pays|paying|payment|send|sending|transfer|transferring|transferred|"
    r"deposit|depositing|remit|remitting)\b",
    re.IGNORECASE,
)
_INBOUND_MONEY_RE = re.compile(r"\b(?:stipend|salary|salaries|reimburs\w*)\b", re.IGNORECASE)

URGENCY_PATTERNS = [
    r"\burgent(?:ly)?\b",
    r"\bimmediately\b",
    r"\basap\b",
    r"\bwithin\s+\d+\s*(?:hours?|hrs?|days?)\b",
    r"\b(?:offer|seat|slot|position)s?\s+(?:will\s+)?(?:expire|lapse|be\s+cancell?ed|be\s+forfeited|get\s+cancell?ed)",
    r"\bexpires?\s+(?:today|in)\b",
    r"\blimited\s+(?:seats?|slots?)\b",
    r"\blast\s+date\b",
    r"\b(?:by|before)\s+(?:today|tonight|eod|end\s+of\s+(?:the\s+)?day)\b",
]
_URGENCY_RE = re.compile("|".join(f"(?:{p})" for p in URGENCY_PATTERNS), re.IGNORECASE)

# Abbreviations whose trailing '.' must not end a sentence ("Rs. 5,000", "Pvt. Ltd.").
_ABBREVIATIONS = {"rs", "no", "pvt", "ltd", "mr", "mrs", "ms", "dr", "inc", "co", "st", "vs", "etc", "e.g", "i.e"}
_BOUNDARY_RE = re.compile(r"[.!?]+\s+|\n[ \t]*\n\s*")

UPI_BEFORE_WINDOW = 120
UPI_AFTER_WINDOW = 60
URGENCY_WINDOW = 250
UPI_PHRASE_WINDOW = 200


def sentence_spans(text: str) -> List[Tuple[int, int]]:
    """Return (start, end) offsets of sentences. Single newlines do not split."""
    spans, start = [], 0
    for m in _BOUNDARY_RE.finditer(text):
        if m.group(0)[0] == ".":
            word = re.search(r"([A-Za-z.]+)$", text[start:m.start()])
            if word and word.group(1).lower().rstrip(".") in _ABBREVIATIONS:
                continue
        spans.append((start, m.end()))
        start = m.end()
    if start < len(text):
        spans.append((start, len(text)))
    return spans


def _sentence_of(spans: List[Tuple[int, int]], pos: int) -> Tuple[int, int]:
    for s, e in spans:
        if s <= pos < e:
            return s, e
    return spans[-1] if spans else (0, pos + 1)


def _is_negated(text: str, sent_start: int, phrase_start: int) -> bool:
    """True if a negation precedes the phrase in its sentence with no cancelling word after it."""
    prefix = text[sent_start:phrase_start]
    negations = list(_NEGATION_RE.finditer(prefix))
    if not negations:
        return False
    between = prefix[negations[-1].end():]
    return not _CANCEL_RE.search(between)


def _find_phrase_demands(text: str, spans) -> List[Dict[str, Any]]:
    demands = []
    for m in _SCAM_RE.finditer(text):
        s, _ = _sentence_of(spans, m.start())
        if _is_negated(text, s, m.start()):
            continue
        demands.append({"kind": "phrase", "match": re.sub(r"\s+", " ", m.group(0).strip()),
                        "start": m.start(), "end": m.end()})
    return demands


def _find_upi_demands(text: str, spans) -> List[Dict[str, Any]]:
    demands = []
    for h in _UPI_RE.finditer(text):
        s, e = _sentence_of(spans, h.start())
        before_lo = max(s, h.start() - UPI_BEFORE_WINDOW)
        after_hi = min(e, h.end() + UPI_AFTER_WINDOW)

        verb = None
        verbs_before = list(_PAY_VERB_RE.finditer(text, before_lo, h.start()))
        if verbs_before:
            verb = verbs_before[-1]
        else:
            verb = _PAY_VERB_RE.search(text, h.end(), after_hi)
        if not verb:
            continue

        lo, hi = min(verb.start(), h.start()), max(verb.end(), h.end())
        # Context window: the span plus the rest of its window inside the sentence.
        context = text[before_lo:after_hi]
        if _INBOUND_MONEY_RE.search(context):
            continue
        if _is_negated(text, s, lo):
            continue
        demands.append({"kind": "upi", "match": f"'{verb.group(0)}' near a UPI handle", "start": lo, "end": hi})
    return demands


def _attach_upi_to_phrase_demands(text: str, phrase_demands: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Report nearby VPAs as payment instructions when a phrase demand is present."""
    attached = []
    for handle in _UPI_RE.finditer(text):
        for demand in phrase_demands:
            distance = max(demand["start"] - handle.end(), handle.start() - demand["end"], 0)
            if distance > UPI_PHRASE_WINDOW:
                continue
            lo = max(0, min(handle.start(), demand["start"]) - UPI_PHRASE_WINDOW)
            hi = min(len(text), max(handle.end(), demand["end"]) + UPI_PHRASE_WINDOW)
            if _INBOUND_MONEY_RE.search(text[lo:hi]):
                continue
            attached.append({
                "kind": "upi_instruction",
                "match": f"UPI payment instruction: {handle.group(0)}",
                "start": handle.start(),
                "end": handle.end(),
            })
            break
    return attached


def _urgency_near(text: str, demands: List[Dict[str, Any]]) -> List[str]:
    found: List[str] = []
    for d in demands:
        lo = max(0, d["start"] - URGENCY_WINDOW)
        hi = min(len(text), d["end"] + URGENCY_WINDOW)
        for m in _URGENCY_RE.finditer(text, lo, hi):
            term = re.sub(r"\s+", " ", m.group(0).strip().lower())
            if term not in found:
                found.append(term)
    return found


def detect_payment_demand(facts: Dict[str, Any]) -> Dict[str, Any]:
    """Rule-based scan of the offer text for upfront payment demands."""
    raw_text = get_field_value(facts, "raw_text") or ""
    if not raw_text:
        return {
            "check_name": "payment_detection",
            "status": "not_applicable",
            "score": 0.0,
            "demands": [],
            "urgency": [],
            "details": "No offer text available to scan for payment demands.",
        }

    spans = sentence_spans(raw_text)
    phrase_demands = _find_phrase_demands(raw_text, spans)
    demands = phrase_demands + _attach_upi_to_phrase_demands(raw_text, phrase_demands)
    demands += _find_upi_demands(raw_text, spans)
    urgency = _urgency_near(raw_text, demands)

    if demands:
        phrases = []
        for d in demands:
            if d["match"].lower() not in (p.lower() for p in phrases):
                phrases.append(d["match"])
        details = (
            "Upfront payment demand found by rule-based phrase matching: "
            + "; ".join(f"'{p}'" if not p.startswith("'") else p for p in phrases[:4]) + "."
        )
        if urgency:
            details += " Urgency language near the demand: " + ", ".join(f"'{u}'" for u in urgency) + "."
        details += " Genuine employers do not charge candidates to join."
        return {
            "check_name": "payment_detection",
            "status": "fail",
            "score": 100.0,
            "demands": [d["match"] for d in demands],
            "urgency": urgency,
            "details": details,
        }

    return {
        "check_name": "payment_detection",
        "status": "pass",
        "score": 0.0,
        "demands": [],
        "urgency": [],
        "details": (
            "No upfront payment demand found by the rule-based phrase checks "
            "(negated mentions such as 'no fee is required' are not counted)."
        ),
    }
