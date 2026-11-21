"""
UPI payment requests in text and QR codes (rule-based, offline)

A `upi://pay?pa=<vpa>&pn=<name>&am=<amount>` link, or a QR code that decodes to one, is a
request to send money. In an offer or recruiter chat that is a payment demand, whatever
the surrounding wording says. This module:

  * finds such links in text                       -> find_upi_requests
  * decodes QR codes in an uploaded image (OpenCV) -> qr_payloads
  * lets ingestion append the decoded payload as a text line so every later step sees it

Only the payee address (pa) and amount (am) are read. The payee name (pn) and note (tn)
are ignored and never stored or shown. Nothing here makes a network call.
"""
import re
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlsplit

import cv2
import numpy as np

UPI_URI_RE = re.compile(r"\bupi://(?:pay|mandate)\?[^\s\"'<>]+", re.IGNORECASE)
_VPA_RE = re.compile(r"^[A-Za-z0-9._-]{2,256}@[A-Za-z][A-Za-z0-9.-]{1,63}$")
_AMOUNT_RE = re.compile(r"^\d{1,9}(?:\.\d{1,2})?$")
MAX_QR_PIXELS = 25_000_000


def parse_upi_uri(uri: str) -> Dict[str, Any]:
    """Return {'vpa': str|None, 'amount': str|None}; malformed parts are None."""
    query = parse_qs(urlsplit(uri).query, keep_blank_values=False)
    vpa = (query.get("pa") or [""])[0].strip()
    amount = (query.get("am") or [""])[0].strip()
    return {"vpa": vpa if _VPA_RE.match(vpa) else None,
            "amount": amount if _AMOUNT_RE.match(amount) else None}


def find_upi_requests(text: str) -> List[Dict[str, Any]]:
    """All upi://pay or upi://mandate links in the text, with character offsets."""
    found = []
    for m in UPI_URI_RE.finditer(text or ""):
        parsed = parse_upi_uri(m.group(0).rstrip(".,;)"))
        found.append({**parsed, "start": m.start(), "end": m.end()})
    return found


def qr_payloads(image: np.ndarray) -> List[str]:
    """Decode every QR code OpenCV can read in a BGR image; [] on any failure or oversized image."""
    try:
        if image is None or image.shape[0] * image.shape[1] > MAX_QR_PIXELS:
            return []
        detector = cv2.QRCodeDetector()
        ok, decoded, _, _ = detector.detectAndDecodeMulti(image)
        values = [d for d in (decoded if ok else ()) if d]
        if not values:
            single, _, _ = detector.detectAndDecode(image)
            values = [single] if single else []
        return values
    except Exception:  # decoding is best effort; never break an analysis
        return []


def upi_lines_from_image(image: np.ndarray) -> str:
    """Decoded QR payloads that are UPI payment requests, one per line (other QR content is dropped)."""
    return "\n".join(v.strip() for v in qr_payloads(image) if UPI_URI_RE.match(v.strip()))
