"""
Fact Extraction Service

Parses offer text with regular expressions (plus rapidfuzz for affiliation spelling
variants) and returns structured fields:
- company_name
- sender_email / sender_domain  (the contact address CLAIMED in the text, not mail headers)
- gstin, cin, llpin             (LLPIN only when explicitly labelled "LLPIN")
- monetary_amounts
- account_numbers (bank accounts, UPI VPAs)
- institutional_affiliations    (names MENTIONED in the text; nothing is verified)

Each field is {value, confidence, status}. Fields that could not be found are
returned with value=None and status='failed_extraction' rather than guessed.

Privacy: logs record only which fields were found and the text length,
never the offer text or extracted values.
"""
import re
import logging
from typing import Dict, Any, List, Optional, Tuple
from rapidfuzz import fuzz

from app.utils.email_domains import is_disposable_mailbox, is_free_mailbox, is_upi_handle

logger = logging.getLogger(__name__)

INSTITUTIONAL_KEYWORDS = [
    "IIT Bombay", "IIT Delhi", "IIT Madras", "IIT Kharagpur", "IIT Kanpur",
    "IISc", "NIT Trichy", "NIT Surathkal", "Placement Cell", "AICTE",
    "University Placement Cell", "UGC", "NASSCOM", "Corporate HR Division"
]

# Company-name patterns: a run of capitalised words ending in a company suffix.
# Words are separated by spaces/tabs only, so a match never spans lines.
_CAP_WORDS = r"(?:[A-Z0-9][A-Za-z0-9&.,'-]*[ \t]+){1,8}"
_COMPANY_SUFFIX = r"(?i:Pvt\.?[ \t]*Ltd\.?|Private[ \t]+Limited|Limited|Ltd\.?|Inc\.?|Corp\.?|LLP|Technologies|Services|Solutions|Systems)"
KNOWN_COMPANY_PATTERNS = [
    rf"(?i:company|employer|organization|organisation|from)[ \t]*:[ \t]*({_CAP_WORDS}{_COMPANY_SUFFIX})(?![A-Za-z])",
    rf"\b({_CAP_WORDS}{_COMPANY_SUFFIX})(?![A-Za-z])",
]

# Registration-number patterns (structure only).
GSTIN_PATTERN = re.compile(r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b")
CIN_PATTERN = re.compile(r"\b[UL][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}\b")
# LLPIN is only accepted when explicitly labelled, e.g. "LLPIN: AAB-1234".
# Unlabelled codes such as "OFR-2026" are reference numbers, not LLPINs.
LLPIN_LABELLED_PATTERN = re.compile(
    r"\b(?i:LLPIN)(?:\s*(?i:no\.?|number))?\s*[:#-]?\s*([A-Z]{3}-[0-9]{4})\b"
)

EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})\b")
URL_DOMAIN_PATTERN = re.compile(
    r"(?:https?://|\bwww\.)(?:www\.)?([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})",
    re.IGNORECASE,
)
# Lines addressed TO the candidate: their addresses are not the sender's.
_RECIPIENT_LINE = re.compile(r"^\s*(?:to|cc|bcc)\s*:|^\s*dear\b", re.IGNORECASE)


def create_field_dict(value: Any, confidence: float) -> Dict[str, Any]:
    """Helper to return standardized field extraction dict."""
    if value is not None and (not isinstance(value, (list, str)) or len(value) > 0):
        return {
            "value": value,
            "confidence": round(confidence, 2),
            "status": "extracted"
        }
    return {
        "value": None,
        "confidence": 0.0,
        "status": "failed_extraction"
    }


def extract_company_name(text: str) -> Dict[str, Any]:
    """Extract the claimed company name with regex, falling back to a first-lines heuristic."""
    for pattern in KNOWN_COMPANY_PATTERNS:
        match = re.search(pattern, text)
        if match:
            candidate = match.group(1).strip(" ,.-")
            if 3 <= len(candidate) <= 80:
                return create_field_dict(candidate, 0.90)

    lines = [line.strip() for line in text.split('\n') if line.strip()]
    for line in lines[:5]:
        if any(term in line.lower() for term in ["ltd", "limited", "pvt", "corp", "technologies", "services", "solutions"]):
            if len(line) <= 80:
                return create_field_dict(line, 0.75)

    return create_field_dict(None, 0.0)


def select_sender_email(text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Choose the sender/contact address claimed in the text.

    Rules:
      1. Ignore addresses on lines starting with To:/Cc:/Bcc:/Dear (the candidate).
      2. Ignore UPI handles (name@ybl, name@paytm, ...).
      3. If any remaining address is a free or disposable mailbox, choose it (that is the risk signal);
         otherwise choose the first remaining address.
      4. If there is none, fall back to the first www./https:// domain (no email).
    Returns (email, domain).
    """
    candidates: List[Tuple[str, str]] = []
    for line in text.splitlines():
        if _RECIPIENT_LINE.match(line):
            continue
        for m in EMAIL_PATTERN.finditer(line):
            domain = m.group(1).lower()
            if is_upi_handle(domain):
                continue
            candidates.append((m.group(0), domain))

    if candidates:
        for email, domain in candidates:
            if is_free_mailbox(domain) or is_disposable_mailbox(domain):
                return email, domain
        return candidates[0]

    url = URL_DOMAIN_PATTERN.search(text)
    if url:
        return None, url.group(1).lower()
    return None, None


def extract_emails_and_domains(text: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Extract sender email and sender domain (see select_sender_email for rules)."""
    email_val, domain_val = select_sender_email(text)
    email_dict = create_field_dict(email_val, 0.90 if email_val else 0.0)
    domain_dict = create_field_dict(domain_val, (0.90 if email_val else 0.70) if domain_val else 0.0)
    return email_dict, domain_dict


def extract_registration_numbers(text: str) -> Dict[str, Dict[str, Any]]:
    """Extract GSTIN, CIN and (labelled) LLPIN. Structure only; nothing is verified here."""
    gstin = GSTIN_PATTERN.search(text)
    cin = CIN_PATTERN.search(text)
    llpin = LLPIN_LABELLED_PATTERN.search(text)

    return {
        "gstin": create_field_dict(gstin.group(0) if gstin else None, 0.98 if gstin else 0.0),
        "cin": create_field_dict(cin.group(0) if cin else None, 0.98 if cin else 0.0),
        "llpin": create_field_dict(llpin.group(1) if llpin else None, 0.95 if llpin else 0.0)
    }


def extract_monetary_amounts(text: str) -> Dict[str, Any]:
    """Extract monetary amounts (e.g. INR 25,000, Rs 35000, 4.5 LPA)."""
    patterns = [
        r'(?:\brs\.?|\binr|₹)\s*[\d,]+(?:\.\d{2})?(?:\s*(?:per\s*month|pm|PA|LPA|stipend|deposit))?',
        r'\b\d+(?:\.\d+)?\s*(?:LPA|Lacs|Lakhs)\b'
    ]

    found = []
    for p in patterns:
        for m in re.findall(p, text, re.IGNORECASE):
            clean_m = m.strip()
            if clean_m not in found:
                found.append(clean_m)

    return create_field_dict(found if found else None, 0.92 if found else 0.0)


def extract_account_numbers(text: str) -> Dict[str, Any]:
    """Extract bank account numbers and UPI VPAs."""
    vpas = []
    for m in re.finditer(r'\b[A-Za-z0-9._-]{2,}@([A-Za-z]+)\b(?!\.[A-Za-z])', text):
        if is_upi_handle(m.group(1)):
            vpas.append(m.group(0))

    bank_accs = re.findall(r'\b(?:account\s*(?:no|number)?\s*:?\s*)(\d{9,18})\b', text, re.IGNORECASE)

    all_accounts = vpas + bank_accs
    return create_field_dict(all_accounts if all_accounts else None, 0.90 if all_accounts else 0.0)


def extract_institutional_affiliations(text: str) -> Dict[str, Any]:
    """Find institution names MENTIONED in the text. A mention is not a verification."""
    found = []
    lower = text.lower()
    for inst in INSTITUTIONAL_KEYWORDS:
        if inst.lower() in lower:
            found.append(inst)

    if not found:
        words = text.split()
        for i in range(len(words) - 1):
            chunk = f"{words[i]} {words[i+1]}"
            for inst in INSTITUTIONAL_KEYWORDS:
                if fuzz.ratio(chunk.lower(), inst.lower()) > 85:
                    found.append(inst)
                    break

    return create_field_dict(sorted(set(found)) if found else None, 0.88 if found else 0.0)


def extract_facts(raw_text: str) -> Dict[str, Any]:
    """
    Main fact extraction function.
    Returns a structured dictionary with confidence per field. Fields that could not be
    extracted have value=None and status='failed_extraction'.
    """
    if not raw_text or not isinstance(raw_text, str):
        raw_text = ""

    company = extract_company_name(raw_text)
    email, domain = extract_emails_and_domains(raw_text)
    regs = extract_registration_numbers(raw_text)
    monetary = extract_monetary_amounts(raw_text)
    accounts = extract_account_numbers(raw_text)
    institutional = extract_institutional_affiliations(raw_text)

    result = {
        "raw_text": raw_text,
        "company_name_legacy": company["value"],
        "domain": domain["value"],
        "company_name": company,
        "sender_email": email,
        "sender_domain": domain,
        "gstin": regs["gstin"],
        "cin": regs["cin"],
        "llpin": regs["llpin"],
        "monetary_amounts": monetary,
        "account_numbers": accounts,
        "institutional_affiliations": institutional,
    }

    # Privacy: log only field presence and text length, never content.
    logger.debug(
        "[FACT_EXTRACTION] text_length=%d company=%s email=%s domain=%s gstin=%s cin=%s llpin=%s "
        "monetary=%s accounts=%s institutional=%s",
        len(raw_text),
        company["value"] is not None, email["value"] is not None, domain["value"] is not None,
        regs["gstin"]["value"] is not None, regs["cin"]["value"] is not None,
        regs["llpin"]["value"] is not None, monetary["value"] is not None,
        accounts["value"] is not None, institutional["value"] is not None,
    )

    return result
