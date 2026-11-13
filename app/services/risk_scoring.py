"""
Risk Scoring Service — rule_based_v2

A fixed, hand-written points table over the three check results. There is no
machine-learning model, no training data and no learned weights.

Risk points (added):
  +65  Upfront payment demand            (HARD OVERRIDE: final score >= 61 -> high risk)
  +20  Urgency language within 250 chars of the payment demand
  +30  Contact domain failed (free mailbox, no MX/NXDOMAIN, lookalike, < 30 days old)
  +25  Registration number failed structural checks
  +10  Registration number structurally valid but NOT verified against any registry
  +10  GSTIN PAN name-initial character conflicts with the claimed company name
  +15  MCA incorporation date contradicts a founding-year/age claim by >1 year
  +30  DMARC fail, or absent DMARC with both SPF and DKIM failing
  +25  Corporate From with free-mailbox or unrelated Reply-To
  +25  Protected-brand display name from a non-official domain
  +15  Body-claimed domain differs from the .eml From domain
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
or sender check), cap at 60 and add: "Reported by other students; not enough
independent evidence to call this high risk."

Low-risk guard: "likely legitimate" requires ALL of:
  - contact domain check passed;
  - registration number is present and did not fail; and
  - at least one externally verified signal: a registry pass marked as checked
    against MCA data, or an authenticated sender from an original .eml with DMARC
    pass and aligned DKIM.
Structural checks alone (including a passing domain and checksum-valid GSTIN)
do not meet this guard. A score <= 30 without an external signal is raised to 31
with an explanatory factor. In DEMO_MODE only, an explicitly configured and
labelled synthetic registry fixture may exercise the positive demo path; it is
not an external verification.

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
    demo_registry_fixture = (
        os.getenv("DEMO_MODE") == "1"
        and reg_status == "pass"
        and reg.get("demo_registry_fixture") is True
    )
    has_external_signal = registry_verified or sender_authenticated or demo_registry_fixture

    factors: List[str] = []
    payment_points = 0.0
    other_points = 0.0

    # Payment
    has_payment = pay_status == "fail"
    if has_payment:
        payment_points += W_PAYMENT
        demands = pay.get("demands") or []
        shown = f": {', '.join(repr(d) for d in demands[:3])}" if demands else ""
        factors.append(f"Upfront payment demand detected ({_fmt(W_PAYMENT)}){shown}")
        urgency = pay.get("urgency") or []
        if urgency:
            payment_points += W_URGENCY
            factors.append(f"Urgency language near the payment demand ({_fmt(W_URGENCY)}): {', '.join(urgency)}")

    # Domain
    if domain_status == "fail":
        other_points += W_DOMAIN_FAIL
        factors.append(f"Contact domain failed checks ({_fmt(W_DOMAIN_FAIL)}): {domain.get('details', '')}".rstrip(": "))

    # Registration number
    if reg_status == "fail":
        other_points += W_REG_FAIL
        factors.append(f"Registration number failed structural checks ({_fmt(W_REG_FAIL)}): {reg.get('details', '')}".rstrip(": "))
    elif reg_present and reg_status != "pass":
        other_points += W_REG_UNVERIFIED
        factors.append(
            f"Registration number is structurally valid but was not verified against the GST/MCA registry "
            f"({_fmt(W_REG_UNVERIFIED)})"
        )
    elif not reg_present:
        other_points += W_REG_MISSING
        factors.append(f"No GSTIN, CIN or LLPIN in the offer ({_fmt(W_REG_MISSING)})")
    consistency_points = float(reg.get("consistency_risk_points", 0) or 0)
    if consistency_points:
        other_points += consistency_points
        for note in (reg.get("details") or "").split("."):
            if "+10" in note or "+15" in note:
                factors.append(note.strip())
    auth_points = float(auth.get("risk_points", 0) or 0)
    if auth_points:
        other_points += auth_points
        factors.append(f"Sender authentication risk (+{auth_points:g}): {auth.get('details', '')}")
    community = by_name.get("community_reports", {})
    community_points = min(40.0, max(0.0, float(community.get("risk_points", community.get("score", 0)) or 0)))
    if community_points:
        other_points += community_points
        factors.append(f"Community report signals (+{community_points:g}): {community.get('details', '')}")

    no_usable_domain = domain_status in ("not_applicable", "insufficient_information")
    if no_usable_domain and not reg_present:
        other_points += W_NO_IDENTIFIERS
        factors.append(f"No usable contact domain and no registration number to check ({_fmt(W_NO_IDENTIFIERS)})")

    # Offsets: only against non-payment points.
    if domain_status == "pass":
        reduction = min(G_DOMAIN_PASS, other_points)
        if reduction > 0:
            other_points -= reduction
            factors.append(f"Contact domain passed DNS checks ({_fmt(-reduction)}, offsets non-payment points only)")
    if reg_status == "pass" and not demo_registry_fixture:
        reduction = min(G_REGISTRY_PASS, other_points)
        if reduction > 0:
            other_points -= reduction
            factors.append(f"MCA registry pass ({_fmt(-reduction)})")
        else:
            factors.append(f"MCA registry pass ({_fmt(-G_REGISTRY_PASS)} offset; score floor is 0)")
    if auth.get("status") == "pass" and auth.get("dmarc_status") == "pass" and auth.get("dkim_aligned") is True:
        reduction = min(10.0, other_points)
        if reduction > 0:
            other_points -= reduction
        applied = f"applied {_fmt(-reduction)}" if reduction < 10.0 else _fmt(-reduction)
        factors.append(f"DMARC pass with aligned DKIM ({_fmt(-10.0)} signal; {applied}, non-payment only)")

    unbounded_score = payment_points + other_points
    score = unbounded_score
    if has_payment and score < PAYMENT_FLOOR:
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
        score = min(score, 60.0)
        factors.append("Reported by other students; not enough independent evidence to call this high risk.")

    # Guard: no structural-only or demo-less checks can establish legitimacy.
    if score <= 30:
        missing = []
        if domain_status != "pass":
            missing.append("the contact domain did not pass")
        if not reg_present:
            missing.append("no registration number was given")
        elif reg_status == "fail":
            missing.append("the registration number failed checks")
        if not has_external_signal:
            missing.append("no externally verified registry match or authenticated sender was found")
        if missing:
            score = GUARD_SCORE
            factors.append(
                f"Raised to {GUARD_SCORE:g}: 'likely legitimate' requires a passing domain, a valid "
                f"registration number, and an externally verified signal, but {' and '.join(missing)}"
            )
        elif demo_registry_fixture:
            factors.append(
                "Low-risk demo fixture applied: the configured synthetic registry fixture is not a live verification."
            )

    risk_band = band_for(score)
    category = {BAND_LEGIT: "likely_legitimate", BAND_MANUAL: "insufficient_evidence_verify_manually",
                BAND_HIGH: "high_risk"}[risk_band]

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
    }
