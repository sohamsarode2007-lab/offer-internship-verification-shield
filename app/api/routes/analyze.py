import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, HTTPException, status
from sqlalchemy.orm import Session

from app.api.limiter import limiter, RATE_LIMIT
from app.db.database import get_db
from app.models.models import Offer, VerificationResult, CheckResult
from app.schemas.schemas import AnalyzeResponse, CheckResultSchema, CheckStatus
from app.services import (
    ingestion,
    fact_extraction,
    domain_verification,
    gstin_verification,
    payment_detection,
    risk_scoring
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["analyze"])

MAX_TEXT_CHARS = 50_000
MAX_FILE_BYTES = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "bmp", "tiff", "txt"}


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
    Accepts offer text and/or one document (pdf, png, jpg, jpeg, bmp, tiff, txt).
    Runs ingestion -> fact extraction -> domain / registration / payment checks ->
    rule_based_v2 scoring.

    Privacy (DPDP): the offer text and file name are NOT stored; only the verdict
    and per-check results are persisted.
    """
    if not text and not file:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Either 'text' form field or 'file' upload must be provided.")

    if text and len(text) > MAX_TEXT_CHARS:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
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
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                                f"File is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.")

    # Step 1: Ingestion
    try:
        raw_text, _ = ingestion.ingest_offer(text=text, file_bytes=file_bytes, filename=filename)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Could not read the document: {e}")
    if not raw_text or not raw_text.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "No text could be extracted from the submission.")

    # Steps 2-5: extraction and checks
    facts = fact_extraction.extract_facts(raw_text)
    domain_check = domain_verification.verify_domain(facts)
    gstin_check = gstin_verification.verify_gstin(facts)
    payment_check = payment_detection.detect_payment_demand(facts)
    check_dicts = [domain_check, gstin_check, payment_check]

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

    return AnalyzeResponse(
        offer_id=offer_id,
        overall_risk_score=overall_risk_score,
        completeness_percentage=completeness_percentage,
        checks=check_schemas,
        summary=summary_msg,
        risk_band=risk_band,
        risk_factors=scoring_res["risk_factors"],
        scoring_model=scoring_res["scoring_model"],
    )
