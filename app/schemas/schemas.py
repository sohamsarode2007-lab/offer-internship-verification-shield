import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field

class CheckStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"
    INSUFFICIENT_INFORMATION = "insufficient_information"

class CheckResultSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    check_name: str
    status: CheckStatus
    score: Optional[float] = None
    details: Optional[str] = None

class VerificationResultSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    offer_id: Optional[int] = None
    overall_risk_score: float = Field(..., ge=0.0, le=100.0)
    completeness_percentage: float = Field(..., ge=0.0, le=100.0)
    created_at: Optional[datetime.datetime] = None
    check_results: List[CheckResultSchema] = []

class OfferSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    title: Optional[str] = None
    company_name: Optional[str] = None
    raw_text: Optional[str] = None
    file_path: Optional[str] = None
    created_at: Optional[datetime.datetime] = None

class Reason(BaseModel):
    """One plain-language 'Why' row: text for people and its score impact ('+65', '−10' or None)."""
    text: str
    impact: Optional[str] = None


class AnalyzeResponse(BaseModel):
    offer_id: Optional[int] = None
    overall_risk_score: float
    completeness_percentage: float
    checks: List[CheckResultSchema]
    summary: str
    # Additive fields (rule_based_v2). Existing fields above are unchanged.
    risk_band: Optional[str] = None
    risk_factors: List[str] = []
    # Plain-language version of risk_factors for the result screen.
    reasons: List[Reason] = []
    scoring_model: Optional[str] = None
    next_steps: List[str] = []
    complaint_summary: str = ""
    report_token: Optional[str] = None
    reportable_indicators: List[dict] = Field(default_factory=list)
    # Not displayed by the frontend. Which company-master snapshot produced the
    # registry result: "synthetic" (demo-only fictional data), "mca_csv", or None
    # when no registry record was consulted. Keeps demo results traceable.
    registry_source: Optional[str] = None
    # Company name extracted from the offer text, shown under the verdict. Returned in
    # the response only; it is never stored.
    company_name: Optional[str] = None
    # What the person could add to strengthen the check: [{id, title, why, how}].
    evidence_hints: List[dict] = Field(default_factory=list)
    # Official look-ups the person can run themselves: [{id, title, number, url, why, steps, caution}].
    self_checks: List[dict] = Field(default_factory=list)
