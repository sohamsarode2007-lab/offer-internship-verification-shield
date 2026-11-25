"""
Evidence hints: what the person could add to make a check stronger (rule-based, deterministic)

Looks only at which checks could not run, never at the offer text. Each hint says what to add,
why it helps and how to get it. No hint is returned when a payment demand was found, because
no extra evidence can change that verdict.
"""
from typing import Dict, List


def _status(checks: List[dict], name: str) -> dict:
    return next((c for c in checks if c.get("check_name") == name), {})


def build_evidence_hints(checks: List[dict], *, had_file: bool = False, had_image: bool = False) -> List[Dict[str, str]]:
    if _status(checks, "payment_detection").get("status") == "fail":
        return []
    hints = []
    if _status(checks, "sender_authentication").get("status") == "not_applicable" and not had_file:
        hints.append({
            "id": "original_email", "title": "Add the original email (.eml)",
            "why": "It lets us read its sender-check results (SPF, DKIM, DMARC), which a pasted copy cannot show. The file can be edited, so a failure counts against the offer but a pass is not counted as proof.",
            "how": "Gmail: open the message, choose the three dots, then Download message. Upload it as the file."})
    if _status(checks, "domain_verification").get("status") in {"not_applicable", "insufficient_information"}:
        hints.append({
            "id": "sender_email", "title": "Add the sender's email address",
            "why": "Without it we cannot check the sender's domain, which is one of the hardest things to fake.",
            "how": "Copy the full address the offer came from and paste it into the extra text box."})
    gstin = _status(checks, "gstin_verification")
    if gstin.get("status") == "insufficient_information" and not gstin.get("identifier_present"):
        hints.append({
            "id": "company_identifiers", "title": "Add the company's registration details",
            "why": "A CIN or GSTIN can be compared with company records; a name alone cannot.",
            "how": "Look for CIN, GSTIN or PAN in the letter footer or on the company's website, and paste it here."})
    if _status(checks, "scam_text_patterns").get("status") == "fail" and not had_image:
        hints.append({
            "id": "payment_screenshot", "title": "Add any payment QR code or screenshot",
            "why": "If they sent a payment QR code, we can read the payee from it.",
            "how": "Upload the screenshot or image as the file."})
    return hints
