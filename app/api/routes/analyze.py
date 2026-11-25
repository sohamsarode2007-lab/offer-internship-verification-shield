import contextlib
import logging
import os
from typing import List, Optional

from app.api.request_limits import analyze_slot
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, HTTPException, status
from sqlalchemy.orm import Session

from app.api.limiter import limiter, RATE_LIMIT
from app.db.database import get_db
from app.utils.field_utils import get_field_value
from app.schemas.schemas import AnalyzeResponse
from app.services import (
    evidence_hints,
    self_checks,
    safety_playbook,
    link_lookup,
    request_budget,
    multi_file,
    evidence_meta,
    plausibility,
    community_reports,
    institution_dashboard,
    offer_analysis,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["analyze"])

LINK_CHECKS_PER_HOUR = int(os.getenv("LINK_CHECKS_PER_HOUR", "5"))


BAND_LABELS = {
    "likely legitimate": "Likely legitimate",
    "insufficient evidence, verify manually": "Insufficient evidence (verify manually before you proceed)",
    "high risk": "High risk",
}
# Bands for which a student may report the sender to warn others.
REPORTABLE_BANDS = {"high risk", "insufficient evidence, verify manually"}


def build_user_guidance(risk_band: str, checks: list[dict], reasons: list[dict]):
    """Return actionable, non-legal advice without repeating submitted text."""
    if risk_band == "high risk":
        next_steps = [
            "Do not send money or share OTPs, passwords, or banking credentials.",
            "Save the offer, messages, payment instructions, and transaction receipts.",
            "If you've already paid, call the National Cyber Crime Helpline 1930 immediately and report at cybercrime.gov.in.",
            "Also contact your bank or payment app immediately and ask what hold or reversal options are available.",
        ]
    elif risk_band == "likely legitimate":
        next_steps = [
            "Confirm the role and sender through contact details found independently from the offer.",
            "Do not pay a recruitment or training fee; a legitimate employer should not require payment as a condition of getting the job or internship.",
        ]
    else:
        next_steps = [
            "Verify the company and registration directly through official sources before proceeding.",
            "Contact the employer using independently located contact details, not links or numbers in the offer.",
            "Do not pay fees or share sensitive identity or banking information while details remain unverified.",
        ]
    # Concerns are the plain-language reasons that added risk (no engine wording).
    concerns = [r["text"].rstrip(".") for r in reasons if (r.get("impact") or "").startswith("+")][:4]
    summary = (f"Automated review result: {BAND_LABELS.get(risk_band, risk_band)}. " +
               ("Observed concerns: " + "; ".join(dict.fromkeys(concerns)) + "."
                if concerns else "No rule-based warning was detected; independently verify the offer."))
    return next_steps, summary

MAX_TEXT_CHARS = offer_analysis.MAX_TEXT_CHARS
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
    files: List[UploadFile] = File(default=[]),
    link_lookups: bool = Form(False),
    db: Session = Depends(get_db)
):
    """
    Accepts offer text and/or one document (pdf, image, txt, or original .eml).
    Runs ingestion -> fact extraction -> domain / registration / payment checks ->
    rule_based_v2 scoring.

    Privacy (DPDP): the offer text and file name are NOT stored; only the verdict
    and per-check results are persisted.
    """
    with contextlib.contextmanager(analyze_slot)():
        return _analyze_offer_impl(request, text, file, files, link_lookups, db)


def _analyze_offer_impl(
    request: Request,
    text: Optional[str],
    file: Optional[UploadFile],
    files: List[UploadFile],
    link_lookups: bool,
    db: Session,
):
    uploads = [u for u in ([file] if file is not None else []) + list(files or []) if u.filename]
    if not text and not uploads:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Either 'text' form field or 'file' upload must be provided.")

    community_reports.purge_if_due(db)

    if text and len(text) > MAX_TEXT_CHARS:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE,
                            f"Text is longer than {MAX_TEXT_CHARS:,} characters.")

    if len(uploads) > multi_file.MAX_FILES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Send at most {multi_file.MAX_FILES} files at a time.")
    loaded = []  # (file name, bytes): names are used only to pick the reader and are never logged or stored
    for upload in uploads:
        name = upload.filename
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                                f"Unsupported file type. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}.")
        data = upload.file.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE,
                                f"File is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.")
        loaded.append((name, data))
    if len(loaded) > 1 and any(n.lower().endswith(".eml") for n, _ in loaded):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "Send an .eml on its own so its sender checks can run; other files can be checked separately.")
    filename = loaded[0][0] if loaded else None
    try:
        submission = offer_analysis.read_submission(text, loaded)
    except offer_analysis.SubmissionError as e:
        raise HTTPException(e.status_code, e.detail)
    raw_text, email_result = submission.raw_text, submission.email_result

    analysis = offer_analysis.run_checks(db, submission)
    facts, check_dicts, scoring_res = analysis.facts, analysis.check_dicts, analysis.scoring
    report_indicators, signature, gstin_check = analysis.report_indicators, analysis.signature, analysis.gstin_check
    overall_risk_score = scoring_res["overall_risk_score"]
    completeness_percentage = scoring_res["completeness_percentage"]
    risk_band = scoring_res["risk_band"]
    # Informational notes (no score impact); never include submitted values.
    notes = plausibility.collect_notes(raw_text, None)
    pdf_sources = [data for name, data in loaded if name.lower().endswith(".pdf")]
    if email_result:
        pdf_sources.extend(
            att["data"] for att in email_result.get("attachments", []) if att["filename"].lower().endswith(".pdf")
        )
    for data in pdf_sources:
        notes += plausibility.collect_notes("", data)  # file-level notes for each PDF
    # Per-client hourly allowance for outbound link checks (the key is held in memory only, never stored or logged).
    client_key = request.client.host if request.client else "unknown"
    allow_links = link_lookups and request_budget.try_spend_keyed("link", client_key, LINK_CHECKS_PER_HOUR)
    link_result = link_lookup.build_link_checks(raw_text, allow_links)
    if link_lookups and not allow_links:
        link_result["notes"].append("Link checks were skipped because this connection has used its hourly allowance. The rest of the check is unaffected.")
    notes += link_result["notes"]
    duplicate = multi_file.duplicate_note(submission.file_texts)
    if duplicate:
        notes.append(duplicate)
    scoring_res["reasons"] = list(scoring_res["reasons"]) + [
        {"text": note, "impact": None} for note in dict.fromkeys(notes)]

    check_schemas = offer_analysis.to_check_schemas(check_dicts)
    # Rule-based scam category, computed in memory (the text is not stored).
    scam_category = institution_dashboard.classify_scam(check_dicts, raw_text)
    offer_id = offer_analysis.store_result(db, check_schemas, overall_risk_score, completeness_percentage,
                                           risk_band, scam_category)

    summary_msg = (
        f"Analysis completed. Risk Score: {overall_risk_score}/100 ({risk_band.upper()}). "
        f"Completeness: {completeness_percentage}%."
    )
    next_steps, complaint_summary = build_user_guidance(
        risk_band, check_dicts, scoring_res["reasons"]
    )

    # Reporting is offered only for high risk and insufficient evidence, never for a
    # likely-legitimate result. The token carries only the band and rule-based category,
    # so a consented report can be counted on the scam-trends page; nothing is recorded without consent.
    report_token, reportable_indicators = None, []
    if risk_band in REPORTABLE_BANDS:
        report_token, reportable_indicators = community_reports.issue_report_token(
            db, report_indicators, signature,
            band=risk_band, scam_category=scam_category,
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
        reasons=scoring_res["reasons"],
        scoring_model=scoring_res["scoring_model"],
        next_steps=next_steps,
        complaint_summary=complaint_summary,
        report_token=report_token,
        reportable_indicators=reportable_indicators,
        registry_source=gstin_check.get("registry_source"),
        # Returned for display only; never persisted (Offer.company_name stays NULL).
        company_name=get_field_value(facts, "company_name", "company_name_legacy"),
        self_checks=self_checks.build_self_checks(facts, check_dicts),
        safety_actions=safety_playbook.build_safety_actions(check_dicts, raw_text, risk_band, link_result["threat_listed"]),
        evidence_meta=evidence_meta.build_evidence_meta(check_dicts),
        evidence_hints=evidence_hints.build_evidence_hints(
            check_dicts, had_file=bool(email_result),
            had_image=any(
                "." in n and n.lower().rsplit(".", 1)[-1] in {"png", "jpg", "jpeg", "bmp", "tiff"}
                for n in [name for name, _ in loaded]
                + ([att["filename"] for att in email_result.get("attachments", [])] if email_result else [])
            )),
    )
