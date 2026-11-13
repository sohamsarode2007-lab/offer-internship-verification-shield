"""
OCR robustness: render each demo PDF to an image, degrade it (rotate 3 degrees,
Gaussian blur, JPEG quality 30), upload it through the image/OCR path and check the
risk band matches the clean text-layer PDF.

Needs the Tesseract binary (OCR) and pypdfium2 (rendering). Skipped otherwise.
A failing case here is a real band flip caused by OCR: report it, do not loosen it.
"""
import io
import os
import shutil

import pytest

from conftest import DEMO_DIR

if shutil.which("tesseract") is None and not os.getenv("TESSERACT_CMD"):
    pytest.skip("Tesseract OCR binary not installed; OCR robustness tests need it "
                "(apt install tesseract-ocr / Windows: UB-Mannheim build)", allow_module_level=True)
pdfium = pytest.importorskip("pypdfium2", reason="pypdfium2 not installed (requirements-dev.txt)")
from PIL import Image, ImageFilter  # noqa: E402

STEMS = [p.stem for p in sorted(DEMO_DIR.glob("*.pdf"))]
RENDER_DPI = 200


def _render_first_page(pdf_path) -> Image.Image:
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        return doc[0].render(scale=RENDER_DPI / 72).to_pil().convert("RGB")
    finally:
        doc.close()


def _degrade(img: Image.Image, how: str):
    """Return (filename_suffix, bytes)."""
    if how == "clean":
        out = img
    elif how == "rotate3":
        out = img.rotate(3, expand=True, fillcolor="white", resample=Image.BICUBIC)
    elif how == "blur":
        out = img.filter(ImageFilter.GaussianBlur(radius=1.5))
    elif how == "jpeg30":
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=30)
        return "jpg", buf.getvalue()
    else:
        raise ValueError(how)
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return "png", buf.getvalue()


def _band_for_pdf(client, stem):
    pdf = (DEMO_DIR / f"{stem}.pdf").read_bytes()
    r = client.post("/analyze", files={"file": (f"{stem}.pdf", pdf, "application/pdf")})
    assert r.status_code == 200, r.text
    return r.json()["risk_band"]


@pytest.mark.parametrize("how", ["clean", "rotate3", "blur", "jpeg30"])
@pytest.mark.parametrize("stem", STEMS)
def test_degraded_scan_keeps_band(demo_client, stem, how):
    expected = _band_for_pdf(demo_client, stem)
    ext, data = _degrade(_render_first_page(DEMO_DIR / f"{stem}.pdf"), how)
    r = demo_client.post("/analyze", files={"file": (f"{stem}_{how}.{ext}", data, f"image/{ext}")})
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["risk_band"] == expected, (
        f"BAND FLIP for {stem} [{how}]: text-layer PDF={expected!r}, OCR={got['risk_band']!r}; "
        f"factors={got['risk_factors']}"
    )
