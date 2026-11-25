"""Work limits for uploaded documents: pages, characters, time. Fictional content only."""
import io

import pytest
from PIL import Image

from app.services import ingestion


def _text_pdf(pages: int, line: str = "Fictional offer text for testing. " * 3) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    for _ in range(pages):
        c.drawString(40, 800, line)
        c.showPage()
    c.save()
    return buf.getvalue()


def test_text_pdf_over_the_page_limit_is_refused_before_extraction(monkeypatch):
    monkeypatch.setattr(ingestion, "MAX_NATIVE_PDF_PAGES", 3)
    with pytest.raises(ingestion.PdfTooLong, match="limit is 3 pages"):
        ingestion._extract_pdf_text(_text_pdf(5), "t")


def test_text_pdf_at_the_limit_is_read(monkeypatch):
    monkeypatch.setattr(ingestion, "MAX_NATIVE_PDF_PAGES", 3)
    assert "Fictional offer text" in ingestion._extract_pdf_text(_text_pdf(3), "t")


def test_text_collection_stops_at_the_character_budget(monkeypatch):
    monkeypatch.setattr(ingestion, "EXTRACT_CHAR_BUDGET", 500)
    seen = []

    class Page:
        def __init__(self, i):
            self.i = i

        def extract_text(self):
            seen.append(self.i)
            return "x" * 200

    text = ingestion._collect_page_text(Page(i) for i in range(1000))
    assert len(seen) == 3 and len(text) < 1000          # 3 pages cross 500; the other 997 are never touched


def _scanned_pdf(pages: int) -> bytes:
    imgs = [Image.new("RGB", (600, 800), "white") for _ in range(pages)]
    buf = io.BytesIO()
    imgs[0].save(buf, format="PDF", save_all=True, append_images=imgs[1:], resolution=100)
    return buf.getvalue()


def test_scanned_pdf_is_rendered_one_page_at_a_time_with_a_timeout(monkeypatch):
    calls = []
    import pdf2image

    def fake_convert(data, **kw):
        calls.append(kw)
        return [Image.new("RGB", (100, 100), "white")]

    monkeypatch.setattr(pdf2image, "convert_from_bytes", fake_convert)
    monkeypatch.setattr(ingestion, "run_ocr_on_image", lambda img, filename="": "page text")
    text = ingestion._extract_pdf_text(_scanned_pdf(3), "t")
    assert [(c["first_page"], c["last_page"]) for c in calls] == [(1, 1), (2, 2), (3, 3)]
    assert all(c["timeout"] == ingestion.POPPLER_TIMEOUT for c in calls)
    assert text.count("page text") == 3


def test_scanned_pdf_stops_when_the_overall_deadline_passes(monkeypatch):
    import pdf2image
    monkeypatch.setattr(pdf2image, "convert_from_bytes", lambda *a, **k: [Image.new("RGB", (50, 50))])
    monkeypatch.setattr(ingestion, "run_ocr_on_image", lambda img, filename="": "t")
    monkeypatch.setattr(ingestion, "OCR_TOTAL_BUDGET_SECONDS", -1)
    with pytest.raises(ValueError, match="took too long"):
        ingestion._extract_pdf_text(_scanned_pdf(2), "t")


def test_tesseract_timeout_aborts_instead_of_trying_heavier_engines(monkeypatch):
    import sys
    import types
    import numpy as np
    fake = types.ModuleType("pytesseract")
    fake.pytesseract = types.SimpleNamespace(tesseract_cmd="")

    def slow(*a, **k):
        assert k["timeout"] == ingestion.TESSERACT_TIMEOUT
        raise RuntimeError("Tesseract process timeout")

    fake.image_to_string = slow
    monkeypatch.setitem(sys.modules, "pytesseract", fake)
    monkeypatch.setattr(ingestion, "_get_easyocr_reader", lambda: None)
    paddle = types.ModuleType("paddleocr")
    paddle.PaddleOCR = lambda **k: pytest.fail("must not fall through to PaddleOCR after a timeout")
    monkeypatch.setitem(sys.modules, "paddleocr", paddle)
    with pytest.raises(ValueError, match="took too long"):
        ingestion.run_ocr_on_image(np.full((50, 50, 3), 255, np.uint8), filename="t")


def test_oversized_pdf_returns_422_from_the_api(api_client, monkeypatch):
    monkeypatch.setattr(ingestion, "MAX_NATIVE_PDF_PAGES", 2)
    r = api_client.post("/analyze", files={"file": ("o.pdf", _text_pdf(4), "application/pdf")})
    assert r.status_code == 422 and "pages" in r.text
