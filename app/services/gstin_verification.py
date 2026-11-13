"""
GSTIN / CIN / LLPIN Structural Check (offline only)

What this module DOES (no network access):
  - GSTIN: format regex + official mod-36 check character; state code must be
    01-38, 97 or 99; if the claimed company name says Pvt/Private/Ltd/Limited the
    6th GSTIN character (4th PAN character, the holder type) must be 'C' (company).
  - CIN: 21-character format; a "Pvt/Private" name must not carry a PLC (public) CIN.
  - LLPIN: AAA-0000 format.
  - A registration number quoted alongside a free-mailbox contact address is flagged.

What this module does NOT do:
  - It does NOT query the GST portal or the MCA registry. There is no live registry
    integration. A structurally valid number may still be fake, belong to another
    company, or be cancelled. Hence a valid structure is reported as
    "insufficient_information", never "pass".

Status contract:
  - no identifier found            -> insufficient_information, identifier_present=False
  - any structural/consistency problem -> fail, identifier_present=True
  - structurally valid             -> insufficient_information, identifier_present=True
  - pass                           -> ONLY for a real registry match (currently unreachable)
"""
import re
from typing import Dict, Any, List, Optional

from app.utils.field_utils import get_field_value
from app.utils.email_domains import is_free_mailbox

CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

GSTIN_REGEX = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
CIN_REGEX = re.compile(r"^[UL][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$")
LLPIN_REGEX = re.compile(r"^[A-Z]{3}-[0-9]{4}$")

# GST state codes 01-38, plus 97 (Other Territory) and 99 (Centre Jurisdiction).
VALID_STATE_CODES = {f"{i:02d}" for i in range(1, 39)} | {"97", "99"}

_COMPANY_NAME_HINT = re.compile(r"\b(?:pvt|private|ltd|limited)\b", re.IGNORECASE)
_PRIVATE_NAME_HINT = re.compile(r"\b(?:pvt|private)\b", re.IGNORECASE)

REGISTRY_NOTE = "NOT checked against the GST/MCA registry; confirms structure only"


def gstin_check_char(g14: str) -> str:
    """Official GSTIN mod-36 check character for the first 14 characters."""
    total = 0
    for i, c in enumerate(g14[:14]):
        p = CHARS.index(c) * (2 if i % 2 else 1)
        total += p // 36 + p % 36
    return CHARS[(36 - total % 36) % 36]


def gstin_checksum_ok(gstin: str) -> bool:
    """True if the 15-character GSTIN has a correct check character."""
    if not isinstance(gstin, str) or len(gstin) != 15:
        return False
    gstin = gstin.upper()
    if any(c not in CHARS for c in gstin):
        return False
    return gstin_check_char(gstin) == gstin[14]


def lookup_registry(identifier: str, id_type: str) -> None:
    """
    Registry lookup stub. There is NO live GST/MCA registry integration.
    Always returns None. A future integration must return a verified record
    from an official source; never populate this from hand-written data.
    """
    return None


def _gstin_problems(gstin: str, company: Optional[str]) -> List[str]:
    problems = []
    if not GSTIN_REGEX.match(gstin):
        return [f"GSTIN '{gstin}' does not match the GSTIN format"]
    if not gstin_checksum_ok(gstin):
        problems.append(
            f"GSTIN '{gstin}' fails the official check-character test "
            f"(last character should be '{gstin_check_char(gstin)}')"
        )
    if gstin[:2] not in VALID_STATE_CODES:
        problems.append(f"GSTIN '{gstin}' has invalid state code '{gstin[:2]}'")
    if company and _COMPANY_NAME_HINT.search(company) and gstin[5] != "C":
        problems.append(
            f"Claimed name '{company}' is a company (Pvt/Ltd), but GSTIN '{gstin}' "
            f"has holder-type '{gstin[5]}' instead of 'C'"
        )
    return problems


def _cin_problems(cin: str, company: Optional[str]) -> List[str]:
    if not CIN_REGEX.match(cin):
        return [f"CIN '{cin}' does not match the 21-character CIN format"]
    problems = []
    if company and _PRIVATE_NAME_HINT.search(company) and cin[12:15] == "PLC":
        problems.append(f"Claimed name '{company}' is private (Pvt), but CIN '{cin}' is a public-company (PLC) CIN")
    return problems


def _llpin_problems(llpin: str) -> List[str]:
    if not LLPIN_REGEX.match(llpin):
        return [f"LLPIN '{llpin}' does not match the AAA-0000 format"]
    return []


def _result(status: str, identifier_present: bool, details: str,
            identifiers: List[Dict[str, str]], score: Optional[float]) -> Dict[str, Any]:
    return {
        "check_name": "gstin_verification",
        "status": status,
        "identifier_present": identifier_present,
        "identifiers": identifiers,
        "registry_checked": False,
        "score": score,
        "confidence": 0.9 if status == "fail" else 0.0,
        "explanation": details,
        "details": details,
    }


def verify_gstin(facts: Dict[str, Any]) -> Dict[str, Any]:
    """Offline structural check of GSTIN/CIN/LLPIN found in the extracted facts."""
    raw_text = get_field_value(facts, "raw_text") or ""
    claimed_company = get_field_value(facts, "company_name", "company_name_legacy")
    sender_domain = get_field_value(facts, "sender_domain", "domain")
    sender_email = get_field_value(facts, "sender_email") or ""
    if not sender_domain and "@" in sender_email:
        sender_domain = sender_email.split("@")[-1].strip()

    gstin = get_field_value(facts, "gstin")
    cin = get_field_value(facts, "cin")
    llpin = get_field_value(facts, "llpin")
    if not (gstin or cin or llpin) and raw_text and isinstance(facts, dict) and not isinstance(facts.get("gstin"), dict):
        # Facts did not come from fact_extraction; extract here with the same rules.
        from app.services.fact_extraction import extract_registration_numbers
        regs = extract_registration_numbers(raw_text)
        gstin, cin, llpin = (regs[k]["value"] for k in ("gstin", "cin", "llpin"))

    identifiers = [{"type": t, "value": v} for t, v in (("GSTIN", gstin), ("CIN", cin), ("LLPIN", llpin)) if v]

    if not identifiers:
        return _result(
            "insufficient_information", False,
            "No GSTIN, CIN or labelled LLPIN found in the offer text.",
            identifiers, None,
        )

    problems: List[str] = []
    if gstin:
        problems += _gstin_problems(gstin, claimed_company)
    if cin:
        problems += _cin_problems(cin, claimed_company)
    if llpin:
        problems += _llpin_problems(llpin)

    if sender_domain and is_free_mailbox(sender_domain):
        problems.append(
            f"A registration number is quoted, but the contact address uses the free mailbox "
            f"'{sender_domain.lower()}'; registered companies normally use their own domain"
        )

    if problems:
        return _result("fail", True, "; ".join(problems) + ".", identifiers, 0.0)

    # Structurally valid. Try the registry (stub: always None today).
    for ident in identifiers:
        record = lookup_registry(ident["value"], ident["type"])
        if record:
            # Unreachable until a real registry integration exists.
            return _result("pass", True, f"{ident['type']} '{ident['value']}' matched the official registry.",
                           identifiers, 95.0)

    listed = ", ".join(f"{i['type']} {i['value']}" for i in identifiers)
    return _result(
        "insufficient_information", True,
        f"{listed}: format and check character are valid, but {REGISTRY_NOTE}.",
        identifiers, None,
    )
