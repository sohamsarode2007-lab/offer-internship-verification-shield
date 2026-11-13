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
    company, or be cancelled. Outside an explicitly configured demo fixture, a
    valid structure is reported as "insufficient_information", never "pass".

Demo mode: DEMO_REGISTRY_FIXTURES may opt specific CINs into the synthetic fixture file.
A fixture pass is labelled and is never represented as live MCA verification.

Status contract:
  - no identifier found            -> insufficient_information, identifier_present=False
  - any structural/consistency problem -> fail, identifier_present=True
  - structurally valid             -> insufficient_information, identifier_present=True
  - pass                           -> real registry match or explicitly labelled demo fixture
"""
import csv
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from app.utils.field_utils import get_field_value
from app.utils.email_domains import is_free_mailbox

CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

GSTIN_REGEX = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
CIN_REGEX = re.compile(r"^[UL][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$")
LLPIN_REGEX = re.compile(r"^[A-Z]{3}-[0-9]{4}$")

# GST state codes 01-38, plus 97 (Other Territory) and 99 (Centre Jurisdiction).
VALID_STATE_CODES = {f"{i:02d}" for i in range(1, 39)} | {"97", "99"}
GST_STATE_NAMES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan",
    "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh",
    "13": "Nagaland", "14": "Manipur", "15": "Mizoram", "16": "Tripura", "17": "Meghalaya",
    "18": "Assam", "19": "West Bengal", "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh",
    "23": "Madhya Pradesh", "24": "Gujarat", "26": "Dadra and Nagar Haveli and Daman and Diu",
    "27": "Maharashtra", "28": "Andhra Pradesh (old code)", "29": "Karnataka", "30": "Goa",
    "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman and Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh",
}
ROC_STATE_CODES = {"AN": "Andaman and Nicobar Islands", "AP": "Andhra Pradesh", "AR": "Arunachal Pradesh",
    "AS": "Assam", "BR": "Bihar", "CH": "Chandigarh", "CT": "Chhattisgarh", "DL": "Delhi",
    "DN": "Dadra and Nagar Haveli and Daman and Diu", "GA": "Goa", "GJ": "Gujarat", "HP": "Himachal Pradesh",
    "HR": "Haryana", "JH": "Jharkhand", "JK": "Jammu and Kashmir", "KA": "Karnataka", "KL": "Kerala",
    "LD": "Lakshadweep", "MH": "Maharashtra", "ML": "Meghalaya", "MN": "Manipur", "MP": "Madhya Pradesh",
    "MZ": "Mizoram", "NL": "Nagaland", "OD": "Odisha", "PB": "Punjab", "PY": "Puducherry",
    "RJ": "Rajasthan", "SK": "Sikkim", "TG": "Telangana", "TN": "Tamil Nadu", "TR": "Tripura",
    "UP": "Uttar Pradesh", "UT": "Uttarakhand", "WB": "West Bengal"}

_COMPANY_NAME_HINT = re.compile(r"\b(?:pvt|private|ltd|limited)\b", re.IGNORECASE)
_PRIVATE_NAME_HINT = re.compile(r"\b(?:pvt|private)\b", re.IGNORECASE)

REGISTRY_NOTE = "NOT checked against the GST/MCA registry; confirms structure only"
DEMO_REGISTRY_PREFIX = "[DEMO FIXTURE — not a live registry result]"
DEMO_REGISTRY_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2] / "fixtures" / "demo" / "registry_fixtures.csv"
)


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


def lookup_registry(identifier: str, id_type: str) -> Dict[str, Any]:
    """Look up a CIN in the loaded local MCA SQLite database (never network)."""
    if id_type != "CIN":
        return {"lookup_status": "not_supported"}
    db_path = Path(os.getenv("MCA_DB_PATH", "data/mca_master.sqlite3"))
    if not db_path.is_absolute():
        db_path = Path(__file__).resolve().parents[2] / db_path
    if not db_path.is_file():
        return {"lookup_status": "db_missing", "db_path": str(db_path)}
    import sqlite3
    try:
        with sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=2) as db:
            row = db.execute(
                "SELECT cin, company_name, company_status, date_of_registration "
                "FROM mca_companies WHERE cin = ?", (identifier.upper(),)
            ).fetchone()
    except sqlite3.Error:
        return {"lookup_status": "db_missing", "db_path": str(db_path)}
    if not row:
        return {"lookup_status": "not_found", "cin": identifier.upper()}
    return {"lookup_status": "found", "cin": row[0], "company_name": row[1],
            "company_status": row[2], "date_of_registration": row[3]}


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
            identifiers: List[Dict[str, str]], score: Optional[float], **metadata) -> Dict[str, Any]:
    result = {
        "check_name": "gstin_verification",
        "status": status,
        "identifier_present": identifier_present,
        "identifiers": identifiers,
        "registry_checked": False,
        "score": score,
        "confidence": 0.95 if status == "pass" else (0.9 if status == "fail" else 0.0),
        "explanation": details,
        "details": details,
    }
    result.update(metadata)
    return result


def _normalized_company_name(value: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _date_consistency(record: Dict[str, Any]) -> tuple[int, List[str]]:
    raw_date = record.get("date_of_registration")
    if not raw_date:
        return 0, []
    parsed = None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d-%b-%Y"):
        try:
            parsed = datetime.strptime(raw_date, fmt).date()
            break
        except ValueError:
            pass
    if not parsed:
        return 0, []
    age_days = (date.today() - parsed).days
    if 0 <= age_days < 365:
        return 15, [f"MCA incorporation date {raw_date} is less than one year ago (+15)"]
    return 0, [f"MCA incorporation date {raw_date}; company is at least one year old"]


def _gstin_cin_state_note(gstin: Optional[str], cin: Optional[str]) -> Optional[str]:
    if not gstin or not cin:
        return None
    gst_state = GST_STATE_NAMES.get(gstin[:2])
    roc_state = ROC_STATE_CODES.get(cin[6:8])
    if not gst_state or not roc_state:
        return f"GSTIN state code {gstin[:2]} and CIN RoC code {cin[6:8]} are shown for information only."
    relation = "consistent" if gst_state == roc_state else "differ"
    return (f"GSTIN state: {gst_state} ({gstin[:2]}); CIN RoC location: {roc_state} "
            f"({cin[6:8]}): these locations {relation}; informational only, not a verification failure.")


def lookup_demo_registry_fixture(cin: str, claimed_company: Optional[str]) -> Optional[Dict[str, str]]:
    """Return an explicitly opted-in synthetic CIN record in demo mode only."""
    if os.getenv("DEMO_MODE") != "1":
        return None
    configured_cins = {
        value.strip().upper()
        for value in os.getenv("DEMO_REGISTRY_FIXTURES", "").split(",")
        if value.strip()
    }
    cin = cin.upper()
    if cin not in configured_cins:
        return None
    try:
        with DEMO_REGISTRY_FIXTURE_PATH.open(encoding="utf-8", newline="") as source:
            for row in csv.DictReader(source):
                if row.get("cin", "").strip().upper() != cin:
                    continue
                if row.get("synthetic", "").strip().lower() != "true":
                    continue
                fixture_name = row.get("company_name", "").strip()
                if _normalized_company_name(fixture_name) != _normalized_company_name(claimed_company):
                    return None
                return {"cin": cin, "company_name": fixture_name}
    except OSError:
        return None
    return None


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
    consistency_points = 0
    consistency_notes: List[str] = []
    if gstin:
        problems += _gstin_problems(gstin, claimed_company)
    if cin:
        problems += _cin_problems(cin, claimed_company)
    if llpin:
        problems += _llpin_problems(llpin)

    if gstin and claimed_company and len(gstin) == 15:
        initial = next((c.upper() for c in claimed_company if c.isalpha()), None)
        if initial and gstin[6] != initial:
            consistency_points += 10
            consistency_notes.append(
                f"GSTIN PAN name-initial character '{gstin[6]}' does not match claimed company initial '{initial}' (+10)"
            )
    state_note = _gstin_cin_state_note(gstin, cin)
    if state_note:
        consistency_notes.append(state_note)

    if sender_domain and is_free_mailbox(sender_domain):
        problems.append(
            f"A registration number is quoted, but the contact address uses the free mailbox "
            f"'{sender_domain.lower()}'; registered companies normally use their own domain"
        )

    if problems:
        return _result("fail", True, "; ".join(problems + consistency_notes) + ".", identifiers, 0.0,
                       consistency_risk_points=consistency_points)

    # Explicit demo fixtures are opt-in and visibly distinguished from live MCA data.
    if cin:
        fixture = lookup_demo_registry_fixture(cin, claimed_company)
        if fixture:
            return _result(
                "pass", True,
                f"{DEMO_REGISTRY_PREFIX} CIN '{cin}' matched synthetic company "
                f"'{fixture['company_name']}' in the configured demo registry fixture.",
                identifiers, 95.0,
                registry_checked=False,
                verification_source="demo_fixture",
                demo_registry_fixture=True,
            )

    # A CIN is verified only against the loaded local MCA master data.
    if cin:
        record = lookup_registry(cin, "CIN")
        if record["lookup_status"] == "found":
            status_text = (record.get("company_status") or "").strip().lower()
            if status_text in {"struck off", "dissolved", "under liquidation"}:
                return _result("fail", True,
                    f"CIN '{cin}' is listed in MCA data as '{record['company_status']}'.",
                    identifiers, 0.0, registry_checked=True, verification_source="mca_registry")
            registered = record.get("company_name") or ""
            if claimed_company and _normalized_company_name(registered) != _normalized_company_name(claimed_company):
                from rapidfuzz.fuzz import ratio
                if ratio(_normalized_company_name(registered), _normalized_company_name(claimed_company)) < 90:
                    return _result("fail", True,
                        f"CIN '{cin}' is registered to '{registered}', which does not match claimed company '{claimed_company}'.",
                        identifiers, 0.0, registry_checked=True, verification_source="mca_registry")
            age_points, age_notes = _date_consistency(record)
            consistency_points += age_points
            consistency_notes.extend(age_notes)
            return _result("pass", True,
                f"CIN '{cin}' matched active MCA master data for '{registered}'. " + " ".join(consistency_notes),
                identifiers, 95.0, registry_checked=True, verification_source="mca_registry",
                verified_identifier_type="CIN", registry_company_name=registered,
                incorporation_date=record.get("date_of_registration"),
                consistency_risk_points=consistency_points)
        if record["lookup_status"] == "db_missing":
            registry_note = "MCA master database is missing; registry was not checked"
        else:
            registry_note = f"CIN '{cin}' was not found in the loaded MCA master data"
    else:
        registry_note = "no CIN was provided for MCA master-data lookup"

    listed = ", ".join(f"{i['type']} {i['value']}" for i in identifiers)
    return _result(
        "insufficient_information", True,
        f"{listed}: format and check character are valid, but {registry_note}; {REGISTRY_NOTE}. " + " ".join(consistency_notes),
        identifiers, None, consistency_risk_points=consistency_points,
    )
