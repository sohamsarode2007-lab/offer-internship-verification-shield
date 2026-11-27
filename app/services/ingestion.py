"""
Ingestion Service
Handles PDF, image, and raw text document ingestion.
Applies OpenCV preprocessing (deskewing, contrast normalization/CLAHE) for images/PDFs,
OCR text extraction (EasyOCR/pytesseract/PaddleOCR), and character normalization pass
to resolve digit/letter confusion (0/O, 1/I/l).
"""
import contextlib
import contextvars
import re
import io
import time
import logging
import os
import shutil
import numpy as np
import cv2

from app.services import upi_payment
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_EASYOCR_READER = None


def heavy_ocr_enabled() -> bool:
    """EasyOCR and PaddleOCR cannot be interrupted once started, so they run only when the operator opts in
    (HEAVY_OCR=1). Without it, Tesseract (which has a hard time limit) is the only OCR engine."""
    return os.getenv("HEAVY_OCR", "").strip() == "1"


def _get_easyocr_reader():
    global _EASYOCR_READER
    if _EASYOCR_READER is None:
        try:
            import easyocr
            _EASYOCR_READER = easyocr.Reader(['en'], gpu=False, verbose=False)
        except Exception as e:
            logger.warning("[INGESTION][OCR] Failed to initialize EasyOCR: %s", e)
            _EASYOCR_READER = False
    return _EASYOCR_READER if _EASYOCR_READER is not False else None


# OCR often splits an email address around "@" ("careers @quillmere.example",
# "hr @ acme.example"). Rejoin only when the right-hand side is a domain with a TLD,
# so text such as "meet @ 5pm" or "@handle" is never rewritten.
_OCR_SPLIT_EMAIL = re.compile(
    r"(?<![A-Za-z0-9._%+-])([A-Za-z0-9._%+-]+)[ \t]*@[ \t]*([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})\b"
)


def repair_ocr_emails(text: str) -> str:
    """Remove OCR-inserted spaces around '@' in email addresses (OCR output only)."""
    return _OCR_SPLIT_EMAIL.sub(r"\1@\2", text) if text else text


def run_ocr_on_image(image_np: np.ndarray, filename: str = "document") -> str:
    """
    Executes real OCR on a preprocessed image numpy array (EasyOCR -> pytesseract ->
    PaddleOCR) and repairs OCR-split email addresses in the result.
    If all engines fail or produce empty output, raises ValueError.
    """
    return repair_ocr_emails(_run_ocr_engines(image_np, filename))


def _run_ocr_engines(image_np: np.ndarray, filename: str = "document") -> str:
    """
    Executes real OCR on a preprocessed image numpy array.
    Tries EasyOCR -> pytesseract -> PaddleOCR in order.
    Logs which engine was used.
    If all engines fail or produce empty output, raises ValueError.
    """
    if image_np is None or image_np.size == 0:
        raise ValueError(f"Empty image received for '{filename}'")

    preprocessed = preprocess_image_cv2(image_np)

    # 1. EasyOCR (opt-in: no time limit of its own)
    try:
        reader = _get_easyocr_reader() if heavy_ocr_enabled() else None
        if reader:
            lines = reader.readtext(preprocessed, detail=0)
            extracted = "\n".join([str(l).strip() for l in lines if str(l).strip()])
            if extracted and len(extracted.strip()) > 3:
                logger.info("[INGESTION][OCR] EasyOCR extracted %d chars from '%s'.", len(extracted), filename)
                return extracted
    except Exception as eocr_err:
        logger.debug("[INGESTION][OCR] EasyOCR failed for '%s': %s", filename, eocr_err)

    # 2. pytesseract
    try:
        import pytesseract
        from PIL import Image as PILImage
        if shutil.which("tesseract") is None and os.getenv("TESSERACT_CMD"):
            pytesseract.pytesseract.tesseract_cmd = os.environ["TESSERACT_CMD"]
        if len(preprocessed.shape) == 2:
            pil_img = PILImage.fromarray(preprocessed)
        else:
            pil_img = PILImage.fromarray(cv2.cvtColor(preprocessed, cv2.COLOR_BGR2RGB))
        text = pytesseract.image_to_string(pil_img, config='--oem 3 --psm 6', timeout=TESSERACT_TIMEOUT).strip()
        if text and len(text) > 3:
            logger.info("[INGESTION][OCR] pytesseract extracted %d chars from '%s'.", len(text), filename)
            return text
    except RuntimeError as pyt_err:
        if "timeout" in str(pyt_err).lower():
            # Do not fall through to the heavier engines: they have no time limit.
            raise ValueError("reading this image took too long; try a smaller or clearer image") from pyt_err
        logger.debug("[INGESTION][OCR] pytesseract failed for '%s': %s", filename, pyt_err)
    except Exception as pyt_err:
        logger.debug("[INGESTION][OCR] pytesseract failed for '%s': %s", filename, pyt_err)

    # 3. PaddleOCR (opt-in: no time limit of its own)
    try:
        if not heavy_ocr_enabled():
            raise RuntimeError("heavy OCR engines are disabled (set HEAVY_OCR=1 to enable)")
        import paddleocr
        ocr = paddleocr.PaddleOCR(lang='en')
        res = ocr.ocr(preprocessed)
        if res and isinstance(res, list):
            lines = []
            for item in res:
                if isinstance(item, list):
                    for line_info in item:
                        if len(line_info) >= 2 and isinstance(line_info[1], (list, tuple)):
                            lines.append(str(line_info[1][0]))
            extracted = "\n".join(lines).strip()
            if extracted and len(extracted) > 3:
                logger.info("[INGESTION][OCR] PaddleOCR extracted %d chars from '%s'.", len(extracted), filename)
                return extracted
    except Exception as paddle_err:
        logger.debug("[INGESTION][OCR] PaddleOCR failed for '%s': %s", filename, paddle_err)

    raise ValueError(f"OCR text extraction failed for '{filename}': no printable text extracted or OCR engine unavailable")


def preprocess_image_cv2(image_np: np.ndarray) -> np.ndarray:
    """
    OpenCV Preprocessing Pipeline:
    1. Grayscale conversion.
    2. Contrast normalization via CLAHE.
    3. Deskewing using minimum area bounding rectangle.
    """
    if image_np is None or image_np.size == 0:
        return image_np

    # 1. Grayscale conversion
    if len(image_np.shape) == 3:
        gray = cv2.cvtColor(image_np, cv2.COLOR_BGR2GRAY)
    else:
        gray = image_np.copy()

    # 2. Contrast Normalization (CLAHE)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    normalized = clahe.apply(gray)

    # 3. Deskewing
    try:
        _, thresh = cv2.threshold(normalized, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        coords = np.column_stack(np.where(thresh > 0))
        if len(coords) > 50:
            angle = cv2.minAreaRect(coords)[-1]
            if angle < -45:
                angle = -(90 + angle)
            else:
                angle = -angle

            if 0.5 < abs(angle) < 45.0:
                (h, w) = normalized.shape[:2]
                center = (w // 2, h // 2)
                M = cv2.getRotationMatrix2D(center, angle, 1.0)
                normalized = cv2.warpAffine(
                    normalized, M, (w, h), 
                    flags=cv2.INTER_CUBIC, 
                    borderMode=cv2.BORDER_REPLICATE
                )
    except Exception:
        pass

    return normalized


def normalize_ocr_characters(text: str) -> str:
    """
    Post-OCR Character Normalization Pass:
    Corrects OCR digit/letter confusion (0/O, 1/I/l, 5/S) in specific patterns.
    """
    if not text:
        return ""

    # 1. Fix monetary amounts (e.g. INR O,OOO -> INR 0,000 or Rs 2S,OOO -> Rs 25,000).
    # \b stops matches inside words ("Partners", "founders"); the lookahead requires at
    # least one real digit so words like "Solutions" after "Rs" are never rewritten.
    def fix_monetary(match):
        prefix_len = match.start(1) - match.start(0)
        digits = match.group(1)
        fixed_digits = digits.translate(str.maketrans("OoIlSs", "001155"))
        return match.group(0)[:prefix_len] + fixed_digits

    text = re.sub(
        r'\b(?:rs\.?|inr)\s*((?=[0-9OoIlSs,]*\d)[0-9OoIlSs][0-9OoIlSs,]*)',
        fix_monetary, text, flags=re.IGNORECASE,
    )

    # 2. Fix GSTIN digit/letter positional confusion: e.g. 27AAACT1234A1Z9
    def fix_gstin(match):
        raw_gst = match.group(0)
        chars = list(raw_gst)
        # Positions 0-1 must be digits
        for i in [0, 1]:
            if chars[i] in ['O', 'o']: chars[i] = '0'
            elif chars[i] in ['I', 'l']: chars[i] = '1'
        # Positions 2-6 must be letters
        for i in range(2, 7):
            if chars[i] == '0': chars[i] = 'O'
            elif chars[i] == '1': chars[i] = 'I'
        # Positions 7-10 must be digits
        for i in range(7, 11):
            if chars[i] in ['O', 'o']: chars[i] = '0'
            elif chars[i] in ['I', 'l']: chars[i] = '1'
            elif chars[i] in ['S', 's']: chars[i] = '5'
        # Position 11 must be letter
        if chars[11] == '0': chars[11] = 'O'
        elif chars[11] == '1': chars[11] = 'I'
        return "".join(chars)

    text = re.sub(r'\b[0-9OoIl]{2}[A-Z01]{5}[0-9OoIlSs]{4}[A-Z01]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}\b', fix_gstin, text)

    return text


# ── Resource guards (checked BEFORE any decoding / rendering) ─────────────────
MAX_IMAGE_PIXELS = 25_000_000   # 25 MP
MAX_OCR_PAGES = 10
OCR_DPI = 200
MIN_NATIVE_TEXT_CHARS = 20


def check_image_pixels(file_bytes: bytes) -> None:
    """Read only the image header and reject images above MAX_IMAGE_PIXELS."""
    from PIL import Image, UnidentifiedImageError
    try:
        with Image.open(io.BytesIO(file_bytes)) as im:
            width, height = im.size
    except (UnidentifiedImageError, OSError) as e:
        raise ValueError("file could not be decoded as an image") from e
    if width * height > MAX_IMAGE_PIXELS:
        raise ValueError(
            f"image is {width}x{height} ({width * height / 1e6:.1f} MP); the limit is {MAX_IMAGE_PIXELS / 1e6:.0f} MP"
        )


def check_pdf_ocr_limits(file_bytes: bytes) -> int:
    """
    Validate a PDF before rendering it for OCR: at most MAX_OCR_PAGES pages, and no page
    that would exceed MAX_IMAGE_PIXELS at OCR_DPI. Returns the page count.
    """
    from pypdf import PdfReader
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        pages = list(reader.pages)
    except Exception as e:
        raise ValueError("PDF could not be read") from e
    if len(pages) > MAX_OCR_PAGES:
        raise ValueError(
            f"scanned PDF has {len(pages)} pages; OCR is limited to {MAX_OCR_PAGES} pages"
        )
    scale = OCR_DPI / 72.0
    for i, page in enumerate(pages, start=1):
        w_pt, h_pt = float(page.mediabox.width), float(page.mediabox.height)
        pixels = (w_pt * scale) * (h_pt * scale)
        if pixels > MAX_IMAGE_PIXELS:
            raise ValueError(
                f"PDF page {i} would render to {pixels / 1e6:.1f} MP at {OCR_DPI} dpi; "
                f"the limit is {MAX_IMAGE_PIXELS / 1e6:.0f} MP"
            )
    return len(pages)


QR_SCAN_DPI = 150
QR_SCAN_MAX_PAGES = 3


def _pdf_upi_qr_lines(file_bytes: bytes, doc: str) -> str:
    """Best effort: UPI payment QR codes on the first pages of a PDF, held in memory only.

    Never raises: a PDF that cannot be rendered simply yields no QR lines.
    """
    try:
        import pdf2image
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(file_bytes))
        pages = min(len(reader.pages), QR_SCAN_MAX_PAGES)
        for page in list(reader.pages)[:pages]:
            w_pt, h_pt = float(page.mediabox.width), float(page.mediabox.height)
            scale = QR_SCAN_DPI / 72.0
            if (w_pt * scale) * (h_pt * scale) > upi_payment.MAX_QR_PIXELS:
                return ""
        images = pdf2image.convert_from_bytes(file_bytes, dpi=QR_SCAN_DPI, first_page=1, last_page=pages,
                                              timeout=POPPLER_TIMEOUT)
        found = []
        for img in images:
            lines = upi_payment.upi_lines_from_image(cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR))
            if lines:
                found.append(lines)
        return "\n".join(found)
    except Exception as e:
        logger.info("[INGESTION] %s: PDF QR scan skipped (%s).", doc, type(e).__name__)
        return ""


MAX_NATIVE_PDF_PAGES = 60          # text-layer PDFs longer than this are refused before any extraction
EXTRACT_CHAR_BUDGET = 60_000       # stop collecting text once this many characters exist (route limit is 50,000)
POPPLER_TIMEOUT = 30               # seconds per rendered page (pdf2image/pdftoppm)
TESSERACT_TIMEOUT = 20             # seconds per OCR call
OCR_TOTAL_BUDGET_SECONDS = 90      # whole-document OCR deadline, checked between pages
_OCR_DEADLINE: contextvars.ContextVar[Optional[float]] = contextvars.ContextVar("ocr_deadline", default=None)


@contextlib.contextmanager
def shared_ocr_budget(seconds: float = OCR_TOTAL_BUDGET_SECONDS):
    """Share one OCR deadline across multiple files/attachments in a single submission."""
    if _OCR_DEADLINE.get() is not None:
        yield
        return
    token = _OCR_DEADLINE.set(time.monotonic() + seconds)
    try:
        yield
    finally:
        _OCR_DEADLINE.reset(token)


class PdfTooLong(ValueError):
    """Refused on purpose (HTTP 422); other parser errors still fall back to the next reader."""


def _collect_page_text(pages) -> str:
    """Join page text but stop as soon as the character budget is spent, so a huge text layer is never built."""
    parts, total = [], 0
    for page in pages:
        chunk = page.extract_text() or ""
        parts.append(chunk)
        total += len(chunk) + 1
        if total > EXTRACT_CHAR_BUDGET:
            break
    return "\n".join(parts).strip()


def _extract_pdf_text(file_bytes: bytes, doc: str) -> str:
    """Text-layer PDF first (pdfplumber, then pypdf); OCR only for scanned PDFs, within limits."""
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            if len(pdf.pages) > MAX_NATIVE_PDF_PAGES:
                raise PdfTooLong(f"PDF has {len(pdf.pages)} pages; the limit is {MAX_NATIVE_PDF_PAGES} pages")
            text = _collect_page_text(pdf.pages)
        if len(text) >= MIN_NATIVE_TEXT_CHARS:
            logger.info("[INGESTION] %s: native text via pdfplumber (%d chars).", doc, len(text))
            return text
    except PdfTooLong:
        raise
    except Exception as e:
        logger.warning("[INGESTION] %s: pdfplumber failed (%s).", doc, type(e).__name__)

    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(file_bytes))
        if len(reader.pages) > MAX_NATIVE_PDF_PAGES:
            raise PdfTooLong(f"PDF has {len(reader.pages)} pages; the limit is {MAX_NATIVE_PDF_PAGES} pages")
        text = _collect_page_text(reader.pages)
        if len(text) >= MIN_NATIVE_TEXT_CHARS:
            logger.info("[INGESTION] %s: native text via pypdf (%d chars).", doc, len(text))
            return text
    except PdfTooLong:
        raise
    except Exception as e:
        logger.warning("[INGESTION] %s: pypdf failed (%s).", doc, type(e).__name__)

    # Scanned PDF: guard first (raises ValueError -> HTTP 422), then render and OCR one page at a time so memory
    # stays at one page and the whole job stays inside a deadline.
    page_count = check_pdf_ocr_limits(file_bytes)
    import pdf2image
    deadline = _OCR_DEADLINE.get()
    if deadline is None:
        deadline = time.monotonic() + OCR_TOTAL_BUDGET_SECONDS
    ocr_pages = []
    for idx in range(1, page_count + 1):
        if time.monotonic() > deadline:
            raise ValueError("reading this scanned PDF took too long; try fewer pages or a text-based PDF")
        try:
            images = pdf2image.convert_from_bytes(file_bytes, dpi=OCR_DPI, first_page=idx, last_page=idx,
                                                  timeout=POPPLER_TIMEOUT)
        except Exception as e:
            raise ValueError(f"scanned PDF could not be rendered for OCR ({type(e).__name__})") from e
        try:
            # pdf2image gives RGB; the OpenCV pipeline expects BGR.
            page_text = run_ocr_on_image(cv2.cvtColor(np.array(images[0]), cv2.COLOR_RGB2BGR), filename=f"{doc} p{idx}")
            if page_text:
                ocr_pages.append(page_text)
        except ValueError as e:
            logger.warning("[INGESTION] %s: OCR failed on page %d (%s).", doc, idx, e)
        if sum(len(t) for t in ocr_pages) > EXTRACT_CHAR_BUDGET:
            break
    text = "\n".join(ocr_pages).strip()
    logger.info("[INGESTION] %s: OCR text (%d chars, %d pages).", doc, len(text), page_count)
    return text


def ingest_offer(
    text: Optional[str] = None,
    file_bytes: Optional[bytes] = None,
    filename: Optional[str] = None,
) -> Tuple[str, Optional[str]]:
    """
    Accepts PDF, image, or raw text input and returns (normalized_text, filename).

    Raises ValueError (HTTP 422 in the route) when a document cannot be read or
    exceeds the OCR limits (25 MP per image/page, 10 pages for scanned PDFs).
    The file name is never logged (it can contain the candidate's name).
    """
    raw_text = text or ""

    if file_bytes and filename:
        ext = filename.lower().rsplit('.', 1)[-1]
        doc = f"<{ext} upload>"

        if ext in ('png', 'jpg', 'jpeg', 'bmp', 'tiff'):
            # Any failure here (too large, undecodable, no OCR engine, empty OCR output)
            # surfaces as ValueError, which the /analyze route turns into HTTP 422.
            ocr_deadline = _OCR_DEADLINE.get()
            if ocr_deadline is not None and time.monotonic() > ocr_deadline:
                raise ValueError("reading uploaded documents took too long; try fewer or clearer images")
            check_image_pixels(file_bytes)
            try:
                img = cv2.imdecode(np.frombuffer(file_bytes, np.uint8), cv2.IMREAD_COLOR)
                if img is None:
                    raise ValueError("file could not be decoded as an image")
                extracted_str = run_ocr_on_image(img, filename=doc)
            except ValueError:
                logger.error("[INGESTION] %s: image OCR failed.", doc)
                raise
            except Exception as img_err:
                logger.error("[INGESTION] %s: image OCR error (%s).", doc, type(img_err).__name__)
                raise ValueError(f"Could not extract text from the image: {type(img_err).__name__}") from img_err
            qr_lines = upi_payment.upi_lines_from_image(img)
            if qr_lines:
                extracted_str = f"{extracted_str}\n{qr_lines}"
            raw_text = f"{raw_text}\n{extracted_str}" if raw_text else extracted_str

        elif ext == 'pdf':
            extracted_pdf = _extract_pdf_text(file_bytes, doc)
            qr_lines = _pdf_upi_qr_lines(file_bytes, doc)
            if qr_lines:
                extracted_pdf = f"{extracted_pdf}\n{qr_lines}".strip()
            if not extracted_pdf:
                logger.error("[INGESTION] %s: no text extracted.", doc)
            raw_text = f"{raw_text}\n{extracted_pdf}" if raw_text else extracted_pdf

        else:
            content_str = file_bytes.decode('utf-8', errors='ignore')
            raw_text = f"{raw_text}\n{content_str}".strip()

    return normalize_ocr_characters(raw_text.strip()), filename


