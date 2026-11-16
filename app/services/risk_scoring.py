"""
Risk Scoring Service — rule_based_v2

A fixed, hand-written points table over the three check results. There is no
machine-learning model, no training data and no learned weights.

Risk points (added):
  +65  Upfront payment demand            (HARD OVERRIDE: final score >= 61 -> high risk)
  +20  Urgency language within 250 chars of the payment demand
  +30  Contact domain failed (free mailbox, disposable mailbox, not the named employer's published recruitment domain, no MX/NXDOMAIN, lookalike, < 30 days old)
  +25  Registration number failed structural checks (GSTIN, CIN, LLPIN, labelled PAN, Udyam format)
  +10  Registration number structurally valid but NOT verified against any registry
  +10  GSTIN PAN name-initial character conflicts with the claimed company name
  +15  MCA incorporation date contradicts a founding-year/age claim by >1 year
  +30  DMARC fail, or absent DMARC with both SPF and DKIM failing
  +25  Corporate From with free-mailbox or unrelated Reply-To
  +25  Protected-brand display name from a non-official domain
  +15  Body-claimed domain differs from the .eml From domain
  +30  Scam-chat wording, strong tier (paid tasks for likes/reviews, pay-to-withdraw); also
       blocks 'likely legitimate' (raised to 31)
  +15  Scam-chat wording, moderate tier only (recruiter reachable only via WhatsApp/Telegram,
       no-interview or easy-money claims)
  +10  extra when both tiers match (strong + moderate = +40 in total)
  +25  Community indicator reported by 3-9 reports; +40 at 10+ reports
  +25  Community template MinHash similarity >= 0.8
  Community evidence is correlated: highest indicator bucket + template points,
  capped at +40 total (multiple matching identifiers never stack).
  +20  No registration number (GSTIN/CIN/LLPIN) in the text
  +20  No usable domain AND no registration number

Offsets (subtracted, only from NON-payment points; never below the payment points):
  -10  Domain check passed
  -10  Registry match
  -10  DMARC pass with aligned DKIM (never offsets payment points)

Community indicators are risk evidence only; they never satisfy the external
verification guard. Details use threshold buckets and never expose exact counts.
Community evidence alone cannot produce a high-risk result: if it is the only
factor pushing a score above 60 (no payment demand or failed domain, registration,
or sender check), cap at 60 and add: "Reported by other job seekers; not enough
independent evidence to call this high risk."

Low-risk guard: "likely legitimate" requires ALL of:
  - contact domain check passed;
  - registration number is present and did not fail; and
  - at least one externally verified signal: a registry pass marked as checked
    against MCA data, or an authenticated sender from an original .eml with DMARC
    pass and aligned DKIM.
Structural checks alone (including a passing domain and checksum-valid GSTIN)
do not meet this guard. A score <= 30 without an external signal is raised to 31
with an explanatory factor.

Synthetic company-master snapshot (DEMO_MODE only): a snapshot loaded with
`load_mca_master.py --synthetic` is consulted only when DEMO_MODE=1. Its results
use the same weights as a loaded company master (registry match -10 offset,
satisfies the low-risk guard; inactive status or CIN/name mismatch +25), are worded
"Company registry match" without calling the data official, live or MCA data, and
carry registry_source="synthetic" in the API response for traceability.

Bands: 0-30 likely legitimate | 31-60 insufficient evidence, verify manually | 61-100 high risk
"""
import os
from typing import List, Dict, Any, Optional

SCORING_MODEL = "rule_based_v2"

W_PAYMENT = 65.0
W_URGENCY = 20.0
W_DOMAIN_FAIL = 30.0
W_REG_FAIL = 25.0
W_REG_UNVERIFIED = 10.0
W_SCAM_STRONG = 30.0
W_SCAM_MODERATE = 15.0
W_SCAM_BOTH_EXTRA = 10.0
W_REG_MISSING = 20.0
W_NO_IDENTIFIERS = 20.0
G_DOMAIN_PASS = 10.0
G_REGISTRY_PASS = 10.0
PAYMENT_FLOOR = 61.0
GUARD_SCORE = 31.0

BAND_LEGIT = "likely legitimate"
BAND_MANUAL = "insufficient evidence, verify manually"
BAND_HIGH = "high risk"


def band_for(score: float) -> str:
    if score <= 30:
        return BAND_LEGIT
    if score <= 60:
        return BAND_MANUAL
    return BAND_HIGH


def _fmt(points: float) -> str:
    return f"{points:+g}"


def _impact(points: float) -> Optional[str]:
    """Score impact for the 'Why' column: '+65', '−10' (true minus sign), or None for no change."""
    if not points:
        return None
    return f"+{points:g}" if points > 0 else f"−{abs(points):g}"


def _domain_reason(details: str) -> str:
    d = details.casefold()
    if "free mailbox" in d:
        return "The contact email is a free personal mailbox (like Gmail), not a company address"
    if "official recruitment domain" in d:
        return "The sender's email domain is not the one this employer says it recruits from"
    if "disposable" in d:
        return "The contact email comes from a temporary throwaway mailbox service"
    if "lookalike" in d:
        return "The email domain imitates another company's name"
    if "registered only" in d or "newly registered" in d:
        return "The email domain was registered only days ago"
    return "The email domain doesn't exist or can't receive email"


def _registration_fail_reason(details: str) -> str:
    import re as _re
    match = _re.match(r"Company is (.+?) in company registry records", details)
    if match:
        return f"The company is listed as {match.group(1).lower()} in the company register"
    if details.startswith("CIN belongs to a different company"):
        return "The registration number (CIN) belongs to a different company"
    if "free mailbox" in details.casefold():
        return "A registration number is given, but replies go to a free personal mailbox"
    return "The registration number isn't valid"


def _community_reason(details: str) -> str:
    parts = []
    if "10+ people" in details:
        parts.append("Reported by 10+ people")
    elif "3+ people" in details:
        parts.append("Reported by 3+ people")
    if "similar to a reported scam template" in details:
        parts.append("the wording matches a scam letter other job seekers reported" if parts
                     else "The wording matches a scam letter other job seekers reported")
    return "; ".join(parts) or "Other job seekers reported details from this letter"


def calculate_risk_score(
    check_results: List[Dict[str, Any]],
    facts: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Apply the rule_based_v2 points table. `facts` is accepted for API compatibility."""
    by_name = {c.get("check_name"): c for c in check_results}
    domain = by_name.get("domain_verification", {})
    reg = by_name.get("gstin_verification", {})
    pay = by_name.get("payment_detection", {})

    domain_status = domain.get("status", "not_applicable")
    reg_status = reg.get("status", "insufficient_information")
    reg_present = bool(reg.get("identifier_present", reg_status in ("pass", "fail")))
    pay_status = pay.get("status", "not_applicable")
    auth = by_name.get("sender_authentication", {})
    registry_verified = (
        reg_status == "pass"
        and reg.get("registry_checked") is True
        and reg.get("verification_source") == "mca_registry"
        and reg.get("verified_identifier_type") == "CIN"
    )
    sender_authenticated = (
        auth.get("status") == "pass"
        and auth.get("dmarc_status") == "pass"
        and auth.get("dkim_aligned") is True
    )
    # A synthetic snapshot is only ever consulted in DEMO_MODE (see gstin_verification);
    # there it exercises the same registry-match path as a loaded company master.
    synthetic_registry = (
        os.getenv("DEMO_MODE") == "1"
        and reg_status == "pass"
        and reg.get("registry_checked") is True
        and reg.get("registry_source") == "synthetic"
        and reg.get("verified_identifier_type") == "CIN"
    )
    has_external_signal = registry_verified or sender_authenticated or synthetic_registry

    factors: List[str] = []
    # Plain-language Why rows for people: (text, score impact). No engine wording.
    reasons: List[Dict[str, Optional[str]]] = []

    def reason(text: str, points: float = 0.0):
        reasons.append({"text": text, "impact": _impact(points)})

    payment_points = 0.0
    other_points = 0.0

    # Payment
    has_payment = pay_status == "fail"
    if has_payment:
        payment_points += W_PAYMENT
        demands = pay.get("demands") or []
        shown = f": {', '.join(repr(d) for d in demands[:3])}" if demands else ""
        factors.append(f"Upfront payment demand detected ({_fmt(W_PAYMENT)}){shown}")
        reason("The letter asks you to pay money before you join", W_PAYMENT)
        urgency = pay.get("urgency") or []
        if urgency:
            payment_points += W_URGENCY
            factors.append(f"Urgency language near the payment demand ({_fmt(W_URGENCY)}): {', '.join(urgency)}")
            reason(f"It pressures you to pay quickly (\"{urgency[0]}\")", W_URGENCY)

    # Domain
    if domain_status == "fail":
        other_points += W_DOMAIN_FAIL
        factors.append(f"Contact domain failed checks ({_fmt(W_DOMAIN_FAIL)}): {domain.get('details', '')}".rstrip(": "))
        reason(_domain_reason(domain.get("details") or ""), W_DOMAIN_FAIL)

    # Registration number
    if reg_status == "fail":
        other_points += W_REG_FAIL
        kind = "company registry checks" if reg.get("registry_checked") is True else "structural checks"
        factors.append(f"Registration number failed {kind} ({_fmt(W_REG_FAIL)}): {reg.get('details', '')}".rstrip(": "))
        reason(_registration_fail_reason(reg.get("details") or ""), W_REG_FAIL)
    elif reg_present and reg_status != "pass":
        other_points += W_REG_UNVERIFIED
        factors.append(
            f"Registration number is structurally valid but was not verified against the GST/MCA registry "
            f"({_fmt(W_REG_UNVERIFIED)})"
        )
        reason("We couldn't match the registration number to a company record", W_REG_UNVERIFIED)
    elif not reg_present:
        other_points += W_REG_MISSING
        factors.append(f"No GSTIN, CIN or LLPIN in the offer ({_fmt(W_REG_MISSING)})")
        reason("The letter gives no company registration number (GSTIN or CIN)", W_REG_MISSING)
    consistency_points = float(reg.get("consistency_risk_points", 0) or 0)
    if consistency_points:
        other_points += consistency_points
        notes_text = " ".join(reg.get("consistency_notes") or [reg.get("details") or ""])
        if "+10" in notes_text:
            reason("The GST number doesn't match the company's name", 10)
        if "+15" in notes_text:
            reason("The founding year in the letter doesn't match the company's registration date", 15)
        if "consistency_notes" in reg:
            factors.extend(note.strip().rstrip(".") for note in reg["consistency_notes"])
        else:
            for note in (reg.get("details") or "").split("."):
                if "+10" in note or "+15" in note:
                    factors.append(note.strip())
    auth_points = float(auth.get("risk_points", 0) or 0)
    if auth_points:
        other_points += auth_points
        factors.append(f"Sender authentication risk (+{auth_points:g}): {auth.get('details', '')}")
        reason("The email's sender checks failed or point to a different sender", auth_points)
    scam_text = by_name.get("scam_text_patterns", {})
    scam_strong = scam_text.get("status") == "fail" and scam_text.get("tier") == "strong"
    if scam_text.get("status") == "fail":
        families = scam_text.get("families") or []
        has_moderate = any(f in ("chat_only", "easy_money") for f in families)
        scam_points = W_SCAM_STRONG if scam_strong else W_SCAM_MODERATE
        if scam_strong and has_moderate:
            scam_points += W_SCAM_BOTH_EXTRA
        other_points += scam_points
        factors.append(f"Scam-chat wording found (+{scam_points:g}): {scam_text.get('details', '')}")
        reason("The wording matches common WhatsApp/Telegram job-scam patterns", scam_points)
    community = by_name.get("community_reports", {})
    community_points = min(40.0, max(0.0, float(community.get("risk_points", community.get("score", 0)) or 0)))
    if community_points:
        other_points += community_points
        factors.append(f"Community report signals (+{community_points:g}): {community.get('details', '')}")
        reason(_community_reason(community.get("details") or ""), community_points)

    no_usable_domain = domain_status in ("not_applicable", "insufficient_information")
    if no_usable_domain and not reg_present:
        other_points += W_NO_IDENTIFIERS
        factors.append(f"No usable contact domain and no registration number to check ({_fmt(W_NO_IDENTIFIERS)})")
        reason("There's no company email, website or registration number to check", W_NO_IDENTIFIERS)

    # Offsets: only against non-payment points.
    if domain_status == "pass":
        reduction = min(G_DOMAIN_PASS, other_points)
        if reduction > 0:
            other_points -= reduction
            factors.append(f"Contact domain passed DNS checks ({_fmt(-reduction)}, offsets non-payment points only)")
        reason("The company's email domain exists and can receive email", -reduction)
    if reg_status == "pass":
        label = "Company registry match" if synthetic_registry else "MCA registry pass"
        reduction = min(G_REGISTRY_PASS, other_points)
        if reduction > 0:
            other_points -= reduction
            factors.append(f"{label} ({_fmt(-reduction)})")
        else:
            factors.append(f"{label} ({_fmt(-G_REGISTRY_PASS)} offset; score floor is 0)")
        name = reg.get("registry_company_name")
        reason(f"The company is registered and active: {name}" if name else "The company is registered and active",
               -reduction)
    if auth.get("status") == "pass" and auth.get("dmarc_status") == "pass" and auth.get("dkim_aligned") is True:
        reduction = min(10.0, other_points)
        if reduction > 0:
            other_points -= reduction
        applied = f"applied {_fmt(-reduction)}" if reduction < 10.0 else _fmt(-reduction)
        factors.append(f"DMARC pass with aligned DKIM ({_fmt(-10.0)} signal; {applied}, non-payment only)")
        reason("The email really came from the company's own domain", -reduction)

    unbounded_score = payment_points + other_points
    score = unbounded_score
    if has_payment and score < PAYMENT_FLOOR:
        reason("Any request for money makes this high risk", PAYMENT_FLOOR - score)
        score = PAYMENT_FLOOR
        factors.append(f"Payment demand override: score raised to {PAYMENT_FLOOR:g} (high risk)")
    score = max(0.0, min(100.0, score))

    community_alone_crossed_high = (
        not has_payment
        and community_points > 0
        and unbounded_score > 60
        and unbounded_score - community_points <= 60
        and domain_status != "fail"
        and reg_status != "fail"
        and auth.get("status") != "fail"
    )
    if community_alone_crossed_high:
        reason("Reports from other job seekers alone aren't enough to call this high risk", min(score, 60.0) - score)
        score = min(score, 60.0)
        factors.append("Reported by other job seekers; not enough independent evidence to call this high risk.")

    # Guard: no structural-only or demo-less checks can establish legitimacy.
    if score <= 30:
        missing = []
        if domain_status != "pass":
            missing.append("the contact domain did not pass")
        if not reg_present:
            missing.append("no registration number was given")
        elif reg_status == "fail":
            missing.append("the registration number failed checks")
        if scam_strong:
            missing.append("the text matches a known task-scam pattern")
        if not has_external_signal:
            missing.append("no externally verified registry match or authenticated sender was found")
        if missing:
            registration_gap = (not reg_present or reg_status == "fail" or not has_external_signal)
            scam_gap = scam_strong and not registration_gap
            reason("We couldn't verify this company's registration, so we can't call it legitimate yet."
                   if registration_gap else
                   "The wording matches a known task-scam pattern, so we can't call it legitimate."
                   if scam_gap else
                   "We couldn't verify the company's email domain, so we can't call it legitimate yet.",
                   GUARD_SCORE - score)
            score = GUARD_SCORE
            factors.append(
                f"Raised to {GUARD_SCORE:g}: 'likely legitimate' requires a passing domain, a valid "
                f"registration number, and an externally verified signal, but {' and '.join(missing)}"
            )

    risk_band = band_for(score)
    category = {BAND_LEGIT: "likely_legitimate", BAND_MANUAL: "insufficient_evidence_verify_manually",
                BAND_HIGH: "high_risk"}[risk_band]
    if risk_band == BAND_LEGIT and pay_status == "pass":
        reason("No payment was requested")

    total_checks = sum(c.get("status") != "not_applicable" for c in check_results)
    evaluated = [c for c in check_results if c.get("status") in ("pass", "fail")]
    completeness = round(len(evaluated) / total_checks * 100.0, 2) if total_checks else 0.0

    return {
        "overall_risk_score": round(score, 2),
        "completeness_percentage": completeness,
        "category": category,
        "risk_band": risk_band,
        "scoring_model": SCORING_MODEL,
        "risk_factors": factors,
        "reasons": reasons,
    }
