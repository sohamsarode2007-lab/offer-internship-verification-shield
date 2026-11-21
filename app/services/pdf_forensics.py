"""
PDF forensic notes (informational only: never change the score, never run anything in the PDF)

Reads structure and metadata of an uploaded PDF in memory and notes things a genuine offer letter
rarely has. Each is a weak or moderate signal with innocent explanations, so a note is shown in 'Why'
with no score impact:

  active_content   JavaScript, an open/launch action, form-submit action or rich media
  attachments      files embedded inside the PDF
  edited_later     modified more than a day after it was created
  future_date      a creation date in the future
  appended_edits   more than one end-of-file marker (changes appended after the first save)
  mixed_pages      pages of clearly different sizes

Nothing is executed: the file is only parsed. Notes never repeat a metadata value, name or date.
Nothing is stored; the bytes stay in memory for the request.
"""
import io
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional

_ACTIVE_TOKENS = (b"/JavaScript", b"/JS", b"/OpenAction", b"/Launch", b"/SubmitForm", b"/RichMedia", b"/AA")
_EOF_RE = re.compile(rb"%%EOF")
_DATE_RE = re.compile(r"D:(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?")

NOTES = {
    "active_content": "This PDF contains active content (scripts or actions that run when it is opened). A genuine offer letter does not need this. Do not open it with scripting enabled and ask for a plain copy.",
    "attachments": "This PDF has other files embedded inside it. A genuine offer letter rarely does; do not open the embedded files.",
    "edited_later": "This PDF was modified well after it was created. Genuine letters are sometimes edited, so this proves nothing alone, but you can ask the sender for the original.",
    "future_date": "This PDF's creation date is in the future, which is unusual and can mean its details were changed.",
    "appended_edits": "This PDF was saved more than once with changes added on top of the original, which is how edits are often made to an existing document.",
    "mixed_pages": "The pages of this PDF are different sizes, which can mean pages were pasted in from another document.",
}


def _parse_date(value) -> Optional[datetime]:
    m = _DATE_RE.match(str(value or ""))
    if not m:
        return None
    year, month, day, hour, minute, second = (int(g) if g else d for g, d in zip(m.groups(), (0, 1, 1, 0, 0, 0)))
    try:
        return datetime(year, month or 1, day or 1, hour, minute, second, tzinfo=timezone.utc)
    except ValueError:
        return None


def pdf_flags(file_bytes: Optional[bytes], now: Optional[datetime] = None) -> List[str]:
    if not file_bytes or not file_bytes.lstrip()[:5] == b"%PDF-":
        return []
    found = set()
    if any(token in file_bytes for token in _ACTIVE_TOKENS):
        found.add("active_content")
    if len(_EOF_RE.findall(file_bytes)) > 1:
        found.add("appended_edits")
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(file_bytes), strict=False)
        root = reader.trailer["/Root"]
        if "/OpenAction" in root or "/AA" in root:
            found.add("active_content")
        names = root.get("/Names") or {}
        if "/JavaScript" in names:
            found.add("active_content")
        if "/EmbeddedFiles" in names:
            found.add("attachments")
        meta = reader.metadata or {}
        created, modified = _parse_date(meta.get("/CreationDate")), _parse_date(meta.get("/ModDate"))
        current = now or datetime.now(timezone.utc)
        if created and created > current + timedelta(days=1):
            found.add("future_date")
        if created and modified and modified - created > timedelta(days=1):
            found.add("edited_later")
        sizes = {(round(float(p.mediabox.width) / 10), round(float(p.mediabox.height) / 10)) for p in reader.pages[:50]}
        if len(sizes) > 1:
            found.add("mixed_pages")
    except Exception:
        pass  # an unreadable PDF just gets the raw-byte checks above
    order = ["active_content", "attachments", "edited_later", "future_date", "appended_edits", "mixed_pages"]
    return [f for f in order if f in found]


def pdf_notes(file_bytes: Optional[bytes], now: Optional[datetime] = None) -> List[str]:
    return [NOTES[f] for f in pdf_flags(file_bytes, now)]
