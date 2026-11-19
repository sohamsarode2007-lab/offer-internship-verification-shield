"""
Plausibility notes (informational only: never change the score)

Weak signals (the link-pattern notes are in url_evidence.py) that are shown in the 'Why' list with no score impact, because each has
common innocent explanations and none is strong enough to count as evidence on its own:

  salary  A stated pay far above normal for an internship/fresher role
          (monthly Rs 1,00,000 or more, or 30 LPA or more, in a text that mentions
          intern/fresher/trainee/entry level/no experience).
  phone   A +91 number that cannot be an Indian mobile (wrong length or first digit),
          or a contact number with a non-Indian country code.
  pdf     An uploaded PDF last saved by a known online editing or design tool
          (from a fixed list; no other metadata is read or shown).

Notes never repeat the number, amount or any metadata value. Nothing here is stored.
"""
import io
import re
from typing import List, Optional

_FRESHER_RE = re.compile(r"\b(?:intern(?:ship)?|fresher|trainee|entry[-\s]level|no\s+experience)\b", re.I)
_PAY_RE = re.compile(
    r"\b(?:stipend|salary|ctc|pay|package|compensation)\b[^.\n]{0,40}?(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)"
    r"(?:\s*(?:/|per|a)\s*(month|mo|day|week|year|annum))?", re.I)
_LPA_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:lpa|lakhs?\s+per\s+annum)\b", re.I)
_PERIOD_TO_MONTH = {"month": 1, "mo": 1, "day": 30, "week": 4.3, "year": 1 / 12, "annum": 1 / 12}
MONTHLY_LIMIT = 100_000.0
LPA_LIMIT = 30.0

_INTL_RE = re.compile(r"(?<![\w+])\+(\d{1,3})[\s().-]?(\d[\d\s().-]{6,14}\d)(?!\w)")

ONLINE_EDITORS = ("canva", "ilovepdf", "smallpdf", "sejda", "pdfescape", "pdf24", "photoshop", "pdffiller")


def salary_note(text: str) -> Optional[str]:
    if not _FRESHER_RE.search(text):
        return None
    for m in _PAY_RE.finditer(text):
        try:
            amount = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        monthly = amount * _PERIOD_TO_MONTH.get((m.group(2) or "month").lower(), 1)
        if monthly >= MONTHLY_LIMIT:
            return ("The pay stated is unusually high for an internship or fresher role. Very high pay is a "
                    "common bait, though some genuine roles do pay well.")
    for m in _LPA_RE.finditer(text):
        if float(m.group(1)) >= LPA_LIMIT:
            return ("The pay stated is unusually high for an internship or fresher role. Very high pay is a "
                    "common bait, though some genuine roles do pay well.")
    return None


def phone_note(text: str) -> Optional[str]:
    for m in _INTL_RE.finditer(text):
        code, rest = m.group(1), re.sub(r"\D", "", m.group(2))
        if code == "91":
            if len(rest) != 10 or rest[0] not in "6789":
                return "A contact number in the offer is not a valid Indian mobile number format."
        else:
            return "A contact number in the offer has a non-Indian country code, which is unusual for an Indian offer."
    return None


def pdf_metadata_note(file_bytes: Optional[bytes]) -> Optional[str]:
    if not file_bytes:
        return None
    try:
        from pypdf import PdfReader
        meta = PdfReader(io.BytesIO(file_bytes)).metadata or {}
        blob = " ".join(str(meta.get(k) or "") for k in ("/Producer", "/Creator")).lower()
    except Exception:
        return None
    if any(tool in blob for tool in ONLINE_EDITORS):
        return ("This PDF was last saved with an online design or editing tool. Genuine offers are sometimes "
                "edited too, so this proves nothing alone, but you can ask the sender for the original file.")
    return None


def collect_notes(text: str, pdf_bytes: Optional[bytes] = None) -> List[str]:
    from app.services.url_evidence import url_notes  # link-pattern notes are informational too
    notes = [salary_note(text or ""), phone_note(text or ""), pdf_metadata_note(pdf_bytes)] + url_notes(text or "")
    return [n for n in notes if n]
