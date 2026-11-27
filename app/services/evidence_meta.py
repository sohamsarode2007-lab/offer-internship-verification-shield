"""
Evidence metadata: where each check's evidence comes from and how it is used (no values, no offer text)

For every check the response carries a small record so a reader can trace a warning to its source:

  source      what the evidence is based on (offer text, email headers, DNS lookup, local registry
              snapshot, community reports)
  affects     "score" (adds or removes points), "safety_floor" (a payment demand forces high risk),
              or "context" (shown, no score effect)
  confidence  "high" / "medium" / "low" / "none" (none = the check could not tell: unknown, not applicable)
  freshness   "live at check time", "snapshot (date shown in the check details)" or "this offer only"
  rule_version the scoring model that used it
  checked_at  UTC time of this analysis

A failed or missing lookup is "none" confidence, never a pass.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.services.risk_scoring import SCORING_MODEL

_BASE = {
    # check_name: (source, freshness, confidence when pass/fail)
    "domain_verification": ("dns_lookup", "live at check time", "medium"),
    "gstin_verification": ("offer_text_and_local_registry_snapshot", "snapshot (date shown in the check details)", "medium"),
    "payment_detection": ("offer_text", "this offer only", "high"),
    "sender_authentication": ("email_headers", "this offer only", "high"),
    "scam_text_patterns": ("offer_text", "this offer only", "medium"),
    "personal_data_request": ("offer_text", "this offer only", "medium"),
    "community_reports": ("community_reports", "consented reports up to now", "medium"),
}


def build_evidence_meta(checks: List[Dict[str, Any]], now: datetime | None = None) -> List[Dict[str, Any]]:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    for check in checks:
        name = check.get("check_name", "")
        source, freshness, confidence = _BASE.get(name, ("derived_check", "this offer only", "low"))
        status = check.get("status")
        if status not in ("pass", "fail"):
            confidence = "none"
        affects = "score"
        if name == "payment_detection" and status == "fail":
            affects = "safety_floor"
        elif status not in ("pass", "fail"):
            affects = "context"
        out.append({"check_name": name, "source": source, "affects": affects, "confidence": confidence,
                    "freshness": freshness, "rule_version": SCORING_MODEL, "checked_at": stamp})
    return out
