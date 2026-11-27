"""Phase 2 API hardening: rate limit, CORS, upload limits and OCR resource guards."""
import io

import pytest

from app.api.limiter import limiter
from app.api.limiter import configured_rate_limit
from app.services import ingestion


def test_rate_limit_returns_429_after_10_requests(api_client, monkeypatch):
    monkeypatch.setattr(limiter, "enabled", True)
    limiter.reset()
    try:
        codes = [api_client.post("/analyze", data={"text": "Hello"}).status_code for _ in range(11)]
    finally:
        limiter.reset()
    assert codes[:10] == [200] * 10
    assert codes[10] == 429


def test_rate_limit_environment_override(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT", "23/minute")
    assert configured_rate_limit() == "23/minute"


def test_analyze_includes_next_steps_and_complaint_summary(api_client):
    response = api_client.post("/analyze", data={
        "text": "Selected for a job. Pay registration fee Rs 499 to receive your offer."
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["next_steps"]
    assert all(isinstance(step, str) for step in payload["next_steps"])
    assert "Automated review result" in payload["complaint_summary"]
    assert "Do not send money" in payload["next_steps"][0]


def test_rate_limit_default_is_ten_per_minute(monkeypatch):
    monkeypatch.delenv("RATE_LIMIT", raising=False)
    monkeypatch.setenv("DEMO_MODE", "1")  # the removed demo switch must not loosen the limit
    assert configured_rate_limit() == "10/minute"


def test_cors_allows_dev_origin_without_credentials(api_client):
    r = api_client.options("/analyze", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert r.headers.get("access-control-allow-credentials") is None


def test_cors_rejects_unknown_origin(api_client):
    r = api_client.options("/analyze", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in r.headers


def test_oversized_image_rejected_before_decode(api_client, monkeypatch):
    from PIL import Image

    # If the guard failed, cv2.imdecode would be reached; make that loud.
    monkeypatch.setattr(ingestion.cv2, "imdecode", lambda *a, **k: pytest.fail("decoded an oversized image"))
    buf = io.BytesIO()
    Image.new("1", (5001, 5001), 1).save(buf, format="PNG")  # 25.01 MP, tiny file
    r = api_client.post("/analyze", files={"file": ("big.png", buf.getvalue(), "image/png")})
    assert r.status_code == 422
    assert "MP" in r.json()["detail"]


def test_scanned_pdf_over_10_pages_rejected(api_client):
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for _ in range(11):  # blank pages = no text layer -> would need OCR
        c.showPage()
    c.save()
    r = api_client.post("/analyze", files={"file": ("scan.pdf", buf.getvalue(), "application/pdf")})
    assert r.status_code == 422
    assert "10 pages" in r.json()["detail"]


def test_huge_pdf_page_rejected_for_ocr():
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(5000, 5000))  # ~ 482 MP at 200 dpi
    c.showPage()
    c.save()
    with pytest.raises(ValueError, match="MP"):
        ingestion.check_pdf_ocr_limits(buf.getvalue())
