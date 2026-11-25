"""The offer-analysis pipeline, separate from HTTP: read the submission, run the checks, store the verdict.

The route (app/api/routes/analyze.py) validates the request and turns SubmissionError into an HTTP error;
everything else lives here so it can be tested and reused without a web request.
"""
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from app.models.models import CheckResult, Offer, VerificationResult
from app.schemas.schemas import CheckResultSchema, CheckStatus
from app.services.check_types import CheckDict
from app.services import (
    community_reports,
    domain_verification,
    email_auth,
    fact_extraction,
    gstin_verification,
    ingestion,
    institution_dashboard,
    payment_detection,
    risk_scoring,
    scam_text,
)

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 50_000


class SubmissionError(Exception):
    """The submission cannot be analysed; status_code is the HTTP status the route should answer with."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class Submission:
    raw_text: str
    email_result: Optional[dict] = None          # parsed .eml headers/body, in memory only
    file_texts: list = field(default_factory=list)


@dataclass
class Analysis:
    facts: dict
    check_dicts: list
    scoring: dict
    report_indicators: list
    signature: list
    gstin_check: dict


def read_submission(text: Optional[str], loaded: list) -> Submission:
    """Turn pasted text and/or loaded files [(name, bytes)] into one text. Names pick the reader and are never kept."""
    file_bytes, filename = (loaded[0][1], loaded[0][0]) if loaded else (None, None)
    file_texts: list = []
    email_result = None
    try:
        with ingestion.shared_ocr_budget():
            if filename and filename.lower().endswith(".eml"):
                parsed_email = email_auth.parse_eml(file_bytes or b"")
                body_text, _ = ingestion.ingest_offer(text=parsed_email["body_text"])
                parts = [body_text] if body_text else []
                for attachment in parsed_email["attachments"]:
                    extracted, _ = ingestion.ingest_offer(
                        file_bytes=attachment["data"], filename=attachment["filename"])
                    if extracted:
                        parts.append(extracted)
                if text:
                    parts.insert(0, text)
                raw_text = "\n".join(parts).strip()
                if len(raw_text) > MAX_TEXT_CHARS:
                    raise SubmissionError(413, f"Extracted email text is longer than {MAX_TEXT_CHARS:,} characters.")
                email_result = parsed_email
            elif len(loaded) > 1:
                parts = [text] if text else []
                for name, data in loaded:
                    extracted, _ = ingestion.ingest_offer(file_bytes=data, filename=name)
                    if extracted:
                        parts.append(extracted)
                        file_texts.append(extracted)
                raw_text = "\n".join(parts).strip()
            else:
                raw_text, _ = ingestion.ingest_offer(text=text, file_bytes=file_bytes, filename=filename)
    except ValueError as e:
        raise SubmissionError(422, f"Could not read the document: {e}")
    if not raw_text or not raw_text.strip():
        raise SubmissionError(422, "No text could be extracted from the submission.")
    # One limit for every path: pasted text, extracted PDF/image/.txt text, and all parts combined.
    if len(raw_text) > MAX_TEXT_CHARS:
        raise SubmissionError(413, f"The text in your submission is longer than {MAX_TEXT_CHARS:,} characters.")
    return Submission(raw_text=raw_text, email_result=email_result, file_texts=file_texts)


def run_checks(db: Session, submission: Submission) -> Analysis:
    """Extract facts, run every check and score them. Nothing here stores anything."""
    raw_text, email_result = submission.raw_text, submission.email_result
    facts = fact_extraction.extract_facts(raw_text)
    if email_result:
        body_email = facts.get("sender_email", {}).get("value")
        body_domain = facts.get("sender_domain", {}).get("value") if body_email else None
        auth_facts = dict(facts)
        auth_facts["sender_domain"] = {"value": email_result.get("sender_domain")}
        auth_facts["sender_email"] = {"value": None}
        domain_check = domain_verification.verify_domain(auth_facts)
        if body_domain:
            domain_check["details"] += f" Body-claimed domain: '{body_domain}'."
            domain_check["explanation"] = domain_check["details"]
        auth_check = email_auth.verify_sender_authentication(email_result, facts)
    else:
        domain_check = domain_verification.verify_domain(facts)
        auth_check = email_auth.not_applicable()
    gstin_check = gstin_verification.verify_gstin(facts)
    payment_check = payment_detection.detect_payment_demand(facts)
    scam_text_check = scam_text.detect_scam_text(facts)
    report_indicators = community_reports.extract_indicators(raw_text, email_result, payment_check)
    signature = community_reports.minhash_signature(raw_text) if os.getenv("INDICATOR_PEPPER") else []
    community_check = community_reports.lookup_community(db, report_indicators, signature)
    check_dicts: list[CheckDict] = [domain_check, gstin_check, payment_check, auth_check, scam_text_check,
                                    community_check]
    scoring = risk_scoring.calculate_risk_score(check_dicts, facts=facts)
    return Analysis(facts=facts, check_dicts=check_dicts, scoring=scoring, report_indicators=report_indicators,
                    signature=signature, gstin_check=gstin_check)


def to_check_schemas(check_dicts: list) -> list:
    return [CheckResultSchema(check_name=c["check_name"], status=CheckStatus(c["status"]), score=c.get("score"),
                              details=c.get("details") or c.get("explanation")) for c in check_dicts]


def store_result(db: Session, check_schemas: list, overall_risk_score: int, completeness_percentage: int,
                 risk_band: str, scam_category: str) -> Optional[int]:
    """Store the verdict and per-check results only (never the text, file names or identifiers).
    Returns the new offer id, or None if storing failed (the analysis is still returned to the person)."""
    try:
        db_offer = Offer(title=None, company_name=None, raw_text=None, file_path=None)
        db.add(db_offer)
        db.flush()
        db_verification = VerificationResult(
            offer_id=db_offer.id, overall_risk_score=overall_risk_score,
            completeness_percentage=completeness_percentage)
        db.add(db_verification)
        db.flush()
        for c_schema in check_schemas:
            db.add(CheckResult(verification_id=db_verification.id, check_name=c_schema.check_name,
                               status=c_schema.status.value, score=c_schema.score, details=c_schema.details))
        # One anonymous public trend row per check: ISO week, band, category only
        # (no text, identifiers, file name, IP or link to this analysis). See PRIVACY_DESIGN.md.
        institution_dashboard.record_check_observation(
            db, risk_band, scam_category, institution_dashboard.current_iso_week())
        db.commit()
        return db_offer.id
    except Exception as e:
        db.rollback()
        logger.error("[ANALYZE] Could not persist verification result: %s", type(e).__name__)
        return None
