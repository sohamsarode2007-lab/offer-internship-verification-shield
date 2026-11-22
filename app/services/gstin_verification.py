"""
GSTIN / CIN / LLPIN Structural Check (offline structure checks; optional CIN registry lookup)

Network use: only lookup_registry() may call data.gov.in (ogd_registry), and only when
DATA_GOV_IN_API_KEY is set. Everything else here is offline.
registry_source "ogd" means a data.gov.in company-master snapshot answered.

What this module DOES (offline):
  - GSTIN: format regex + official mod-36 check character; state code must be
    01-38, 97 or 99; if the claimed company name says Pvt/Private/Ltd/Limited the
    6th GSTIN character (4th PAN character, the holder type) must be 'C' (company).
  - CIN: 21-character format; a "Pvt/Private" name must not carry a PLC (public) CIN.
  - LLPIN: AAA-0000 format.
  - A registration number quoted alongside a free-mailbox contact address is flagged.

What this module does NOT do:
  - It does NOT query the GST portal or the MCA registry. There is no live registry
    integration. A structurally valid number may still be fake, belong to another
    company, or be cancelled. Without a registry record, a valid structure is
    reported as "insufficient_information", never "pass".

Registry wording (local MCA_CSV snapshot or live data.gov.in record; a snapshot
labelled SYNTHETIC is never consulted):
  - active, name-matched: "Company registry match: <name>; Active; incorporated <date>."
  - inactive status:      "Company is <Status> in company registry records: <name>; incorporated <date>."
  - different company:    "CIN belongs to a different company in company registry records: ..."
The wording never calls the data official, live or MCA data; registry_source
("mca_csv" | "ogd") records which snapshot answered.

Status contract:
  - no identifier found            -> insufficient_information, identifier_present=False
  - any structural/consistency problem -> fail, identifier_present=True
  - structurally valid             -> insufficient_information, identifier_present=True
  - pass                           -> active, name-matched record in a loaded company master
"""
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from app.services import ogd_registry
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


SOURCE_SYNTHETIC = "SYNTHETIC"
SOURCE_MCA_CSV = "MCA_CSV"


def _snapshot_source(db) -> str:
    """Source label from registry_metadata; legacy DBs without metadata count as MCA_CSV."""
    import sqlite3
    try:
        row = db.execute("SELECT value FROM registry_metadata WHERE key='source'").fetchone()
    except sqlite3.Error:
        return SOURCE_MCA_CSV
    return (row[0] if row else SOURCE_MCA_CSV).upper()


def lookup_registry(identifier: str, id_type: str) -> Dict[str, Any]:
    """
    Look up a CIN: the local company-master SQLite database first, then (only when
    DATA_GOV_IN_API_KEY is set) one live data.gov.in lookup by CIN.

    If the live lookup is unavailable (timeout, blocked, bad payload) the local result is
    returned unchanged, so an outage is never reported as "company not found".
    """
    local = _lookup_local(identifier, id_type)
    if (id_type != "CIN" or local["lookup_status"] == "found"
            or not ogd_registry.is_enabled()):
        return local
    status, record = ogd_registry.fetch_company_by_cin(identifier)
    if status == ogd_registry.FOUND and record:
        return {"lookup_status": "found", "cin": record["cin"], "company_name": record["company_name"],
                "company_status": record["company_status"],
                "date_of_registration": record["date_of_registration"], "registry_source": "ogd"}
    if status == ogd_registry.NOT_FOUND:
        return {"lookup_status": "not_found", "cin": identifier.upper(), "registry_source": "ogd"}
    return local


def _lookup_local(identifier: str, id_type: str) -> Dict[str, Any]:
    """Look up a CIN in the loaded local company-master SQLite database (never network).

    A snapshot labelled SYNTHETIC (made-up companies) is always ignored: the lookup
    behaves exactly as if no registry database were loaded.
    """
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
            source = _snapshot_source(db)
            if source == SOURCE_SYNTHETIC:
                return {"lookup_status": "db_missing", "db_path": str(db_path)}
            row = db.execute(
                "SELECT cin, company_name, company_status, date_of_registration "
                "FROM mca_companies WHERE cin = ?", (identifier.upper(),)
            ).fetchone()
    except sqlite3.Error:
        return {"lookup_status": "db_missing", "db_path": str(db_path)}
    registry_source = "mca_csv"
    if not row:
        return {"lookup_status": "not_found", "cin": identifier.upper(), "registry_source": registry_source}
    return {"lookup_status": "found", "cin": row[0], "company_name": row[1],
            "company_status": row[2], "date_of_registration": row[3],
            "registry_source": registry_source}


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


_PAN_REGEX = re.compile(r"^[A-Z]{3}[ABCFGHJLPT][A-Z][0-9]{4}[A-Z]$")
_UDYAM_REGEX = re.compile(r"^UDYAM-[A-Z]{2}-[0-9]{2}-[0-9]{7}$")


def _pan_problems(pan: str, company: Optional[str], gstin: Optional[str]) -> List[str]:
    """PAN format, company holder type ('C'), and agreement with the PAN embedded in a valid GSTIN."""
    if not _PAN_REGEX.match(pan):
        return [f"PAN '{pan}' does not match the PAN format"]
    problems = []
    if company and _COMPANY_NAME_HINT.search(company) and pan[3] != "C":
        problems.append(f"Claimed name '{company}' is a company (Pvt/Ltd), but PAN '{pan}' has holder-type '{pan[3]}' instead of 'C'")
    if gstin and GSTIN_REGEX.match(gstin) and gstin[2:12] != pan:
        problems.append(f"PAN '{pan}' differs from the PAN inside GSTIN '{gstin}'")
    return problems


def _udyam_problems(udyam: str) -> List[str]:
    if not _UDYAM_REGEX.match(udyam):
        return [f"Udyam number '{udyam}' does not match the UDYAM-XX-00-0000000 format"]
    return []


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


_LEGAL_SUFFIXES = {"pvt": "private", "ltd": "limited", "lmtd": "limited"}


def _registry_name_key(value: Optional[str]) -> str:
    """Name key for comparing a letter's company name with a registry name.

    Registry names spell out legal suffixes ("PRIVATE LIMITED") while letters abbreviate
    them ("Pvt. Ltd."); expanding them first stops a genuine match scoring as a different
    company. Only the legal-form words are expanded, so different names still differ.
    """
    words = re.sub(r"[^a-z0-9& ]", " ", (value or "").lower().replace("&", " and ")).split()
    return "".join(_LEGAL_SUFFIXES.get(w, w) for w in words)


def _parse_registry_date(raw_date: Optional[str]) -> Optional[date]:
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(raw_date or "", fmt).date()
        except ValueError:
            pass
    return None


def _date_consistency(record: Dict[str, Any], raw_text: str, source_label: str = "MCA") -> tuple[int, List[str]]:
    raw_date = record.get("date_of_registration")
    if not raw_date:
        return 0, []
    parsed = _parse_registry_date(raw_date)
    if not parsed:
        return 0, []
    claim = re.search(
        r"\b(?:established|founded|since)\s+(\d{4})\b|\b(\d{1,2})\s+years?\b",
        raw_text, re.IGNORECASE,
    )
    if not claim:
        return 0, [f"{source_label} incorporation date {parsed.isoformat()}; no founding-year/age claim to compare (informational only)."]
    if claim.group(1):
        claim_year = int(claim.group(1))
        claim_label = f"founding-year claim {claim_year}"
    else:
        claim_year = date.today().year - int(claim.group(2))
        claim_label = f"age claim {claim.group(2)} years (implied founding year {claim_year})"
    difference = abs(parsed.year - claim_year)
    if difference > 1:
        return 15, [
            f"Contradiction: {claim_label}; {source_label} incorporation date {parsed.isoformat()} "
            f"(year difference {difference}; +15)"
        ]
    return 0, [
        f"{claim_label} is within one year of {source_label} incorporation date {parsed.isoformat()} (no points)."
    ]


def _gstin_cin_state_note(gstin: Optional[str], cin: Optional[str]) -> Optional[str]:
    if not gstin or not cin:
        return None
    gst_state = GST_STATE_NAMES.get(gstin[:2])
    roc_state = ROC_STATE_CODES.get(cin[6:8])
    if not gst_state or not roc_state:
        return f"GSTIN state code {gstin[:2]} and CIN RoC code {cin[6:8]} are shown for information only."
    relation = "are consistent" if gst_state == roc_state else "differ"
    return (f"GSTIN state: {gst_state} ({gstin[:2]}); CIN RoC location: {roc_state} "
            f"({cin[6:8]}): these locations {relation}; informational only, not a verification failure.")


INACTIVE_STATUSES = {"struck off", "dissolved", "under liquidation"}  # exact values; see _is_inactive_status
# Registry status wording varies ("Strike Off", "Under Process of Striking Off", "Liquidated",
# "Amalgamated"), so match word stems. "Dormant" is deliberately not inactive.
_INACTIVE_STEMS = ("strik", "struck", "dissol", "liquidat", "amalgamat")


def _is_inactive_status(status: str) -> bool:
    lowered = (status or "").strip().lower()
    return lowered in INACTIVE_STATUSES or any(stem in lowered for stem in _INACTIVE_STEMS)


def _registry_result(record: Dict[str, Any], claimed_company: Optional[str], raw_text: str,
                     identifiers: List[Dict[str, str]], consistency_points: int,
                     prior_notes: List[str]) -> Dict[str, Any]:
    """
    Result for a CIN found in the loaded company master (MCA_CSV data or a live
    data.gov.in answer). Same wording for both sources:

      pass : "Company registry match: <name>; Active; incorporated <date>."
      fail : "Company is <Status> in company registry records: <name>; incorporated <date>."
             (struck off / dissolved / under liquidation)
      fail : "CIN belongs to a different company in company registry records:
              <name>; status <status>; incorporated <date>."

    Informational notes (state codes, incorporation-date comparison) follow the lead
    sentence. Point-bearing notes (+10 PAN initial, +15 date contradiction) are also
    returned in consistency_notes for scoring. The wording never calls the data
    official, live or MCA data; registry_source says which snapshot answered.
    """
    registered = record.get("company_name") or ""
    status = (record.get("company_status") or "").strip()
    parsed = _parse_registry_date(record.get("date_of_registration"))
    incorporated = parsed.isoformat() if parsed else (record.get("date_of_registration") or "unknown")
    source_key = "ogd" if record.get("registry_source") == "ogd" else "mca_csv"
    metadata = dict(registry_checked=True,
                    verification_source="mca_registry",
                    registry_source=source_key,
                    verified_identifier_type="CIN", registry_company_name=registered,
                    incorporation_date=record.get("date_of_registration"))
    point_notes = [n for n in prior_notes if "+10" in n]
    info_notes = list(prior_notes)  # all notes (informational and point-bearing) follow the lead sentence

    def details(lead: str, extra: List[str]) -> str:
        return " ".join([lead] + [n.rstrip(".") + "." for n in extra if n])

    name_matches = True
    if claimed_company and _registry_name_key(registered) != _registry_name_key(claimed_company):
        from rapidfuzz.fuzz import ratio
        name_matches = ratio(_registry_name_key(registered), _registry_name_key(claimed_company)) >= 90
    if not name_matches:
        lead = (f"CIN belongs to a different company in company registry records: "
                f"{registered}; status {status}; incorporated {incorporated}.")
        return _result("fail", True, details(lead, info_notes), identifiers, 0.0,
                       consistency_risk_points=consistency_points, consistency_notes=point_notes, **metadata)
    if _is_inactive_status(status):
        lead = f"Company is {status} in company registry records: {registered}; incorporated {incorporated}."
        return _result("fail", True, details(lead, info_notes), identifiers, 0.0,
                       consistency_risk_points=consistency_points, consistency_notes=point_notes, **metadata)

    age_points, age_notes = _date_consistency(record, raw_text, source_label="registry")
    lead = f"Company registry match: {registered}; {status}; incorporated {incorporated}."
    return _result("pass", True, details(lead, info_notes + age_notes), identifiers, 95.0,
                   consistency_risk_points=consistency_points + age_points,
                   consistency_notes=point_notes + [n for n in age_notes if "+15" in n], **metadata)


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
    pan = get_field_value(facts, "pan")
    udyam = get_field_value(facts, "udyam")
    if not (gstin or cin or llpin or pan or udyam) and raw_text and isinstance(facts, dict) and not isinstance(facts.get("gstin"), dict):
        # Facts did not come from fact_extraction; extract here with the same rules.
        from app.services.fact_extraction import extract_registration_numbers
        regs = extract_registration_numbers(raw_text)
        gstin, cin, llpin, pan, udyam = (regs[k]["value"] for k in ("gstin", "cin", "llpin", "pan", "udyam"))

    identifiers = [{"type": t, "value": v} for t, v in
                   (("GSTIN", gstin), ("CIN", cin), ("LLPIN", llpin), ("PAN", pan), ("UDYAM", udyam)) if v]

    if not identifiers:
        return _result(
            "insufficient_information", False,
            "No GSTIN, CIN, PAN, Udyam number or labelled LLPIN found in the offer text.",
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
    if pan:
        problems += _pan_problems(pan, claimed_company, gstin)
    if udyam:
        problems += _udyam_problems(udyam)
        if not _udyam_problems(udyam):
            consistency_notes.append("Udyam number format is valid; Udyam numbers are self-declared and are not verified here")

    if gstin and claimed_company and len(gstin) == 15 and gstin_checksum_ok(gstin):
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

    # A CIN is verified only against the loaded local company-master data.
    if cin:
        record = lookup_registry(cin, "CIN")
        if record["lookup_status"] == "found":
            return _registry_result(record, claimed_company, raw_text, identifiers,
                                    consistency_points, consistency_notes)
        if record["lookup_status"] == "db_missing":
            registry_note = "MCA master database is missing; registry was not checked"
        elif record.get("registry_source") == "ogd":
            registry_note = f"CIN '{cin}' was not found in the company registry records"
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
