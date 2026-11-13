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
  +20  No registration number (GSTIN/CIN/LLPIN) in the text
  +20  No usable domain AND no registration number

Offsets (subtracted, only from NON-payment points; never below the payment points):
  -10  Domain check passed
  -10  Registry match (no registry integration exists today, so this never fires)

Guard: "likely legitimate" requires the domain check to pass AND a registration
number that is present and did not fail. Otherwise a score <= 30 is raised to 31.

Bands: 0-30 likely legitimate | 31-60 insufficient evidence, verify manually | 61-100 high risk
"""
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
    if reg_status == "pass":
        reduction = min(G_REGISTRY_PASS, other_points)
        if reduction > 0:
            other_points -= reduction
            factors.append(f"Registration number matched the official registry ({_fmt(-reduction)})")

    score = payment_points + other_points
    if has_payment and score < PAYMENT_FLOOR:
        score = PAYMENT_FLOOR
        factors.append(f"Payment demand override: score raised to {PAYMENT_FLOOR:g} (high risk)")
    score = max(0.0, min(100.0, score))

    # Guard: never call an offer likely legitimate without positive evidence.
    if score <= 30:
        missing = []
        if domain_status != "pass":
            missing.append("the contact domain did not pass")
        if not reg_present:
            missing.append("no registration number was given")
        elif reg_status == "fail":
            missing.append("the registration number failed checks")
        if missing:
            score = GUARD_SCORE
            factors.append(
                f"Raised to {GUARD_SCORE:g}: 'likely legitimate' needs a passing domain and a valid "
                f"registration number, but {' and '.join(missing)}"
            )

    risk_band = band_for(score)
    category = {BAND_LEGIT: "likely_legitimate", BAND_MANUAL: "insufficient_evidence_verify_manually",
                BAND_HIGH: "high_risk"}[risk_band]

    total_checks = len(check_results)
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
