"""Shared shape of one check's result."""
from typing import List, Optional, TypedDict


class CheckDict(TypedDict, total=False):
    """One check's result as the checks produce it and the scorer reads it (each check may add its own keys)."""
    check_name: str
    status: str
    score: Optional[int]
    details: Optional[str]
    explanation: Optional[str]
    # Keys only some checks add; the scorer reads them with .get(), so a missing key means "that check did not say".
    domain: Optional[str]                    # domain_verification: the domain that was checked
    identifier_present: bool                 # gstin_verification: an identifier was found in the text
    registry_checked: bool                   # gstin_verification: a local registry snapshot was consulted
    registry_company_name: Optional[str]     # gstin_verification: company name on the matched registry row
    verification_source: Optional[str]       # gstin_verification: where a verified identifier came from
    verified_identifier_type: Optional[str]  # gstin_verification: "CIN", "GSTIN", ...
    consistency_risk_points: float           # gstin_verification: points for registry-vs-text contradictions
    consistency_notes: List[str]             # gstin_verification: the notes behind those points
    demands: List[str]                       # payment_detection: matched demand phrases (never stored)
    risk_points: float                       # sender_authentication / community_reports: points this check adds
    tier: Optional[str]                      # scam_text_patterns ("strong"/"moderate"), personal_data_request ("bank"/"documents")
    families: List[str]                      # scam_text_patterns / personal_data_request: pattern families matched
    urgency: List[str]                       # payment_detection: urgency phrases near the demand
