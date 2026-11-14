import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, HTTPException, status
from sqlalchemy.orm import Session

from app.api.limiter import limiter, RATE_LIMIT
from app.db.database import get_db
from app.utils.field_utils import get_field_value
from app.models.models import Offer, VerificationResult, CheckResult
from app.schemas.schemas import AnalyzeResponse, CheckResultSchema, CheckStatus
from app.services import (
    ingestion,
    fact_extraction,
    domain_verification,
    gstin_verification,
    payment_detection,
    email_auth,
    risk_scoring,
    community_reports,
    institution_dashboard,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["analyze"])


def build_user_guidance(risk_band: str, checks: list[dict], risk_factors: list[str]):
    """Return actionable, non-legal advice without repeating submitted text."""
    payment = next((c for c in checks if c.get("check_name") == "payment_detection"), {})
    registry = next((c for c in checks if c.get("check_name") == "gstin_verification"), {})
    if payment.get("status") == "fail":
        next_steps = [
            "Do not send money or share OTPs, passwords, or banking credentials.",
            "Save the offer, messages, payment instructions, and transaction receipts.",
            "If you already paid, contact your bank or UPI provider promptly and report the transaction to the official cybercrime channel.",
        ]
    elif risk_band == "likely legitimate":
        next_steps = [
            "Confirm the role and sender through contact details found independently from the offer.",
            "Do not pay recruitment or training fees; legitimate employers should explain any terms in writing.",
        ]
    else:
        next_steps = [
            "Verify the company and registration directly through official sources before proceeding.",
            "Contact the employer using independently located contact details, not links or numbers in the offer.",
            "Do not pay fees or share sensitive identity or banking information while details remain unverified.",
        ]
    concerns = [factor.split(":", 1)[0].rstrip(".") for factor in risk_factors[:3]]
    if registry.get("status") == "fail" and registry.get("details"):
        concerns.insert(0, registry["details"].split(".", 1)[0])
    summary = (f"Automated review result: {risk_band}. " +
               ("Observed concerns: " + "; ".join(dict.fromkeys(concerns)) + "."
                if concerns else "No rule-based warning was detected; independently verify the offer."))
    return next_steps, summary

MAX_TEXT_CHARS = 50_000
MAX_FILE_BYTES = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "bmp", "tiff", "txt", "eml"}


# Plain `def`: DNS, WHOIS and OCR are blocking calls, so FastAPI runs this in its
# threadpool instead of blocking the event loop.
@router.post("/analyze", response_model=AnalyzeResponse, status_code=status.HTTP_200_OK)
@limiter.limit(RATE_LIMIT)
def analyze_offer(
    request: Request,
    text: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    """
    Accepts offer text and/or one document (pdf, image, txt, or original .eml).
    Runs ingestion -> fact extraction -> domain / registration / payment checks ->
    rule_based_v2 scoring.

    Privacy (DPDP): the offer text and file name are NOT stored; only the verdict
    and per-check results are persisted.
    """
    if not text and not file:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Either 'text' form field or 'file' upload must be provided.")

    community_reports.purge_expired(db)

    if text and len(text) > MAX_TEXT_CHARS:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE,
                            f"Text is longer than {MAX_TEXT_CHARS:,} characters.")

    file_bytes = None
    filename = None
    if file is not None and file.filename:
        filename = file.filename
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                                f"Unsupported file type. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}.")
        file_bytes = file.file.read(MAX_FILE_BYTES + 1)
        if len(file_bytes) > MAX_FILE_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE,
                                f"File is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.")

    # Step 1: Ingestion. Parse .eml headers only in memory; only extracted body and
    # supported PDF/image attachments enter the existing check pipeline.
    email_result = None
    try:
        if filename and filename.lower().endswith(".eml"):
            parsed_email = email_auth.parse_eml(file_bytes or b"")
            body_text, _ = ingestion.ingest_offer(text=parsed_email["body_text"])
            parts = [body_text] if body_text else []
            for attachment in parsed_email["attachments"]:
                extracted, _ = ingestion.ingest_offer(
                    file_bytes=attachment["data"], filename=attachment["filename"]
                )
                if extracted:
                    parts.append(extracted)
            if text:
                parts.insert(0, text)
            raw_text = "\n".join(parts).strip()
            if len(raw_text) > MAX_TEXT_CHARS:
                raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE,
                                    f"Extracted email text is longer than {MAX_TEXT_CHARS:,} characters.")
            email_result = parsed_email
        else:
            raw_text, _ = ingestion.ingest_offer(text=text, file_bytes=file_bytes, filename=filename)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Could not read the document: {e}")
    if not raw_text or not raw_text.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "No text could be extracted from the submission.")

    # Steps 2-5: extraction and checks
    facts = fact_extraction.extract_facts(raw_text)
    if email_result:
        body_domain = facts.get("sender_domain", {}).get("value")
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
    report_indicators = community_reports.extract_indicators(raw_text, email_result, payment_check)
    signature = community_reports.minhash_signature(raw_text) if os.getenv("INDICATOR_PEPPER") else []
    community_check = community_reports.lookup_community(db, report_indicators, signature)
    check_dicts = [domain_check, gstin_check, payment_check, auth_check, community_check]

    # Step 6: scoring
    scoring_res = risk_scoring.calculate_risk_score(check_dicts, facts=facts)
    overall_risk_score = scoring_res["overall_risk_score"]
    completeness_percentage = scoring_res["completeness_percentage"]
    risk_band = scoring_res["risk_band"]

    check_schemas = [
        CheckResultSchema(
            check_name=c["check_name"],
            status=CheckStatus(c["status"]),
            score=c.get("score"),
            details=c.get("details") or c.get("explanation"),
        )
        for c in check_dicts
    ]

    # Persistence: verdict + check results only. raw_text / file_path / names are not stored.
    try:
        db_offer = Offer(title=None, company_name=None, raw_text=None, file_path=None)
        db.add(db_offer)
        db.flush()

        db_verification = VerificationResult(
            offer_id=db_offer.id,
            overall_risk_score=overall_risk_score,
            completeness_percentage=completeness_percentage,
        )
        db.add(db_verification)
        db.flush()

        for c_schema in check_schemas:
            db.add(CheckResult(
                verification_id=db_verification.id,
                check_name=c_schema.check_name,
                status=c_schema.status.value,
                score=c_schema.score,
                details=c_schema.details,
            ))
        db.commit()
        offer_id = db_offer.id
    except Exception as e:
        db.rollback()
        logger.error("[ANALYZE] Could not persist verification result: %s", type(e).__name__)
        offer_id = None

    summary_msg = (
        f"Analysis completed. Risk Score: {overall_risk_score}/100 ({risk_band.upper()}). "
        f"Completeness: {completeness_percentage}%."
    )
    next_steps, complaint_summary = build_user_guidance(
        risk_band, check_dicts, scoring_res["risk_factors"]
    )

    # The token carries only the band and rule-based category, so that a consented
    # report can be counted on the VIT Pune dashboard; nothing is recorded without consent.
    report_token, reportable_indicators = community_reports.issue_report_token(
        db, report_indicators, signature,
        band=risk_band, scam_category=institution_dashboard.classify_scam(check_dicts, raw_text),
    )
    if report_token:
        try:
            db.commit()
        except Exception:
            db.rollback()
            report_token, reportable_indicators = None, []

    return AnalyzeResponse(
        offer_id=offer_id,
        overall_risk_score=overall_risk_score,
        completeness_percentage=completeness_percentage,
        checks=check_schemas,
        summary=summary_msg,
        risk_band=risk_band,
        risk_factors=scoring_res["risk_factors"],
        scoring_model=scoring_res["scoring_model"],
        next_steps=next_steps,
        complaint_summary=complaint_summary,
        report_token=report_token,
        reportable_indicators=reportable_indicators,
        registry_source=gstin_check.get("registry_source"),
        # Returned for display only; never persisted (Offer.company_name stays NULL).
        company_name=get_field_value(facts, "company_name", "company_name_legacy"),
    )
