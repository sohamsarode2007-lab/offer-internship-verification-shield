"""UPI QR codes inside PDFs. Payee handles are fictional; PDFs are built in memory."""
import io

import cv2
from PIL import Image

from app.services import ingestion

LINK = "upi://pay?pa=hrdesk@fakepsp&pn=Hiring%20Desk&am=500&cu=INR"


def _qr_pil(payload):
    image = cv2.QRCodeEncoder.create().encode(payload)
    image = cv2.resize(image, None, fx=8, fy=8, interpolation=cv2.INTER_NEAREST)
    image = cv2.copyMakeBorder(image, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=255)
    return Image.fromarray(image).convert("RGB")


def _pdf_with(payload):
    page = Image.new("RGB", (1240, 1754), "white")
    if payload:
        page.paste(_qr_pil(payload), (100, 100))
    buf = io.BytesIO()
    page.save(buf, format="PDF", resolution=150)
    return buf.getvalue()


def test_upi_qr_in_pdf_is_found():
    out = ingestion._pdf_upi_qr_lines(_pdf_with(LINK), "t")
    assert "upi://pay" in out and "hrdesk@fakepsp" in out


def test_non_upi_qr_is_ignored():
    assert ingestion._pdf_upi_qr_lines(_pdf_with("https://careers.example/apply"), "t") == ""


def test_pdf_without_qr_gives_nothing():
    assert ingestion._pdf_upi_qr_lines(_pdf_with(None), "t") == ""


def test_garbage_bytes_fail_soft():
    assert ingestion._pdf_upi_qr_lines(b"not a pdf", "t") == ""


def test_ingest_adds_qr_line_and_it_is_a_payment_demand(monkeypatch):
    from app.services import payment_detection
    monkeypatch.setattr(ingestion, "_extract_pdf_text", lambda b, d: "Welcome aboard. Please confirm your seat.")
    text, _ = ingestion.ingest_offer(file_bytes=_pdf_with(LINK), filename="o.pdf")
    assert "upi://pay" in text
    assert payment_detection.detect_payment_demand({"raw_text": text})["status"] == "fail"
