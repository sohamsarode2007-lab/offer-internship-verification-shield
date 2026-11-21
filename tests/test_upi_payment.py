"""upi:// links and QR codes. The payee addresses are fictional (.example-style handles are not UPI, so a made-up PSP is used)."""
import cv2
import numpy as np
import pytest

from app.services import community_reports as cr, ingestion, payment_detection, upi_payment

LINK = "upi://pay?pa=hrdesk@fakepsp&pn=Hiring%20Desk&am=500&cu=INR"


def qr_image(payload):
    image = cv2.QRCodeEncoder.create().encode(payload)
    image = cv2.resize(image, None, fx=8, fy=8, interpolation=cv2.INTER_NEAREST)
    image = cv2.copyMakeBorder(image, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=255)
    return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)


def test_parse_reads_only_payee_and_amount():
    assert upi_payment.parse_upi_uri(LINK) == {"vpa": "hrdesk@fakepsp", "amount": "500"}


@pytest.mark.parametrize("uri, expected", [
    ("upi://pay?pa=not-a-vpa&am=10", {"vpa": None, "amount": "10"}),
    ("upi://pay?pa=a@b&am=-5", {"vpa": None, "amount": None}),
    ("upi://pay?pa=hr@fakepsp&am=1e9", {"vpa": "hr@fakepsp", "amount": None}),
    ("upi://pay", {"vpa": None, "amount": None}),
])
def test_malformed_parts_become_none(uri, expected):
    assert upi_payment.parse_upi_uri(uri) == expected


def test_find_requests_in_text():
    found = upi_payment.find_upi_requests(f"Confirm your seat: {LINK}.")
    assert len(found) == 1 and found[0]["vpa"] == "hrdesk@fakepsp"
    assert upi_payment.find_upi_requests("We accept UPI and cards. See upi help page.") == []


def test_link_in_text_is_a_payment_demand_and_hides_payee_name():
    result = payment_detection.detect_payment_demand({"raw_text": f"Your seat is reserved. Confirm here: {LINK}"})
    assert result["status"] == "fail"
    assert "UPI payment request" in " ".join(result["demands"])
    assert "Rs 500" in result["details"] and "Hiring" not in result["details"]


def test_text_without_a_link_is_not_flagged_by_this_rule():
    result = payment_detection.detect_payment_demand({"raw_text": "Your stipend is paid through UPI every month."})
    assert result["status"] == "pass"


def test_qr_code_in_image_is_decoded_to_a_text_line():
    assert upi_payment.upi_lines_from_image(qr_image(LINK)) == LINK


def test_non_upi_qr_codes_are_ignored():
    assert upi_payment.upi_lines_from_image(qr_image("https://careers.brightwave.example/apply")) == ""


def test_image_without_qr_gives_nothing():
    assert upi_payment.upi_lines_from_image(np.full((200, 200, 3), 255, np.uint8)) == ""
    assert upi_payment.upi_lines_from_image(None) == ""


def test_ingestion_appends_qr_payload_to_ocr_text(monkeypatch):
    monkeypatch.setattr(ingestion, "run_ocr_on_image", lambda img, filename="x": "Scan to confirm your seat")
    ok, png = cv2.imencode(".png", qr_image(LINK))
    text, _ = ingestion.ingest_offer(file_bytes=png.tobytes(), filename="chat.png")
    assert "Scan to confirm your seat" in text and LINK in text


def test_qr_payee_becomes_a_community_indicator_even_with_an_unlisted_handle(monkeypatch):
    monkeypatch.setenv("INDICATOR_PEPPER", "test-pepper-not-a-secret")
    check = payment_detection.detect_payment_demand({"raw_text": LINK})
    indicators = cr.extract_indicators(LINK, None, check)
    assert [i["indicator_type"] for i in indicators] == ["upi"]
    assert "hiring" not in str(indicators).casefold()


def test_redaction_removes_the_whole_upi_link():
    redacted = cr.redact_text(f"Pay here {LINK} today")
    assert "hrdesk" not in redacted and "Hiring" not in redacted and "<UPI_LINK>" in redacted


def test_analyze_forces_high_risk_for_a_qr_payment_link(api_client):
    body = api_client.post("/analyze", data={"text": f"Offer of internship. Pay to confirm: {LINK}"}).json()
    assert body["risk_band"] == "high risk"
    assert "Hiring" not in str(body)
