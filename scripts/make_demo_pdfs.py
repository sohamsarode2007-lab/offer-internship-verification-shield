"""
Generate offer-letter style A4 PDFs from the demo letters in fixtures/demo/*.txt.

Each PDF has a real text layer (no OCR needed) and a letter layout:
  - company / sender name header (bold, large) and a rule;
  - identifier line(s) under it (CIN / GSTIN / website / note) in small grey type;
  - date right-aligned, subject in bold;
  - salutation and body paragraphs, reflowed to the page width;
  - signature block (closing, name, title / contact).
Layout roles are inferred from the plain-text letter, so the .txt stays the single
source of the wording. All letters are synthetic (fictional companies, .example domains).

Usage (from the project root):
    .\\.venv\\Scripts\\python.exe scripts\\make_demo_pdfs.py

Requires reportlab (requirements-dev.txt).
"""
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas

DEMO_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "demo"

LETTERS = [
    "legit_emberlake",
    "legit_brightpath_young_startup",
    "scam_fake_govt_scheme_fee",
    "registry_name_match_quillmere",
    "registry_struck_off_tarnwick",
    "registry_cin_mismatch_halvorn",
]

MARGIN_X, MARGIN_TOP, MARGIN_BOTTOM = 64, 64, 64
BODY_FONT, BODY_BOLD = "Helvetica", "Helvetica-Bold"
BODY_SIZE, BODY_LEADING = 10.5, 15
INK, GREY, RULE = HexColor("#111111"), HexColor("#555555"), HexColor("#999999")

CLOSINGS = {"regards,", "best,", "sincerely,", "warm regards,", "best regards,", "yours sincerely,"}
SALUTATION = re.compile(r"^(dear|hi|hello)\b", re.IGNORECASE)
META = re.compile(r"^\(|\bCIN\b|\bGSTIN\b|\bwww\.|\|")


@dataclass
class Letter:
    header: List[str] = field(default_factory=list)
    meta: List[str] = field(default_factory=list)
    date: Optional[str] = None
    subject: Optional[str] = None
    salutation: Optional[str] = None
    paragraphs: List[str] = field(default_factory=list)
    closing: Optional[str] = None
    signature: List[str] = field(default_factory=list)


def parse_letter(text: str) -> Letter:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    letter, i = Letter(), 0

    # Header: lines before the first identifier/date/subject/salutation line.
    while i < len(lines) and not (META.search(lines[i]) or lines[i].startswith(("Date:", "Subject:"))
                                  or SALUTATION.match(lines[i])):
        letter.header.append(lines[i]); i += 1
    while i < len(lines) and META.search(lines[i]) and not SALUTATION.match(lines[i]):
        letter.meta.append(lines[i]); i += 1
    while i < len(lines) and lines[i].startswith(("Date:", "Subject:")):
        if lines[i].startswith("Date:"):
            letter.date = lines[i]
        else:
            letter.subject = lines[i]
        i += 1
    if i < len(lines) and SALUTATION.match(lines[i]):
        letter.salutation = lines[i]; i += 1

    rest = lines[i:]
    close_at = next((k for k, line in enumerate(rest) if line.strip().lower() in CLOSINGS), None)
    if close_at is None:
        # No closing word: the signature is the short trailing lines after the last sentence.
        close_at = len(rest)
        while close_at > 0 and not re.search(r"[.!?]$", rest[close_at - 1]) and len(rest[close_at - 1]) < 70:
            close_at -= 1
        body, letter.signature = rest[:close_at], rest[close_at:]
    else:
        body, letter.closing, letter.signature = rest[:close_at], rest[close_at], rest[close_at + 1:]

    # Reflow hard-wrapped body lines; a line ending a sentence ends the paragraph.
    paragraph: List[str] = []
    for line in body:
        paragraph.append(line.strip())
        if re.search(r"[.!?]$", line.strip()):
            letter.paragraphs.append(" ".join(paragraph)); paragraph = []
    if paragraph:
        letter.paragraphs.append(" ".join(paragraph))
    return letter


class _Writer:
    def __init__(self, path: Path, title: str):
        self.width, self.height = A4
        self.c = canvas.Canvas(str(path), pagesize=A4, invariant=1)  # invariant: reproducible bytes
        self.c.setTitle(title)
        self.y = self.height - MARGIN_TOP

    def need(self, space: float):
        if self.y - space < MARGIN_BOTTOM:
            self.c.showPage()
            self.y = self.height - MARGIN_TOP

    def text(self, value: str, font=BODY_FONT, size=BODY_SIZE, leading=BODY_LEADING, color=INK, align="left"):
        usable = self.width - 2 * MARGIN_X
        for part in simpleSplit(value, font, size, usable) or [""]:
            self.need(leading)
            self.c.setFont(font, size)
            self.c.setFillColor(color)
            if align == "right":
                self.c.drawRightString(self.width - MARGIN_X, self.y, part)
            else:
                self.c.drawString(MARGIN_X, self.y, part)
            self.y -= leading

    def gap(self, points: float):
        self.y -= points

    def rule(self):
        self.c.setStrokeColor(RULE)
        self.c.setLineWidth(0.75)
        self.c.line(MARGIN_X, self.y, self.width - MARGIN_X, self.y)

    def save(self):
        self.c.save()


def letter_to_pdf(txt_path: Path, pdf_path: Path) -> None:
    letter = parse_letter(txt_path.read_text(encoding="utf-8"))
    w = _Writer(pdf_path, txt_path.stem)

    for line in letter.header:
        w.text(line, font=BODY_BOLD, size=17, leading=22)
    for line in letter.meta:
        w.text(line, size=8.5, leading=12, color=GREY)
    w.gap(4); w.rule(); w.gap(22)

    if letter.date:
        w.text(letter.date, align="right"); w.gap(10)
    if letter.subject:
        w.text(letter.subject, font=BODY_BOLD); w.gap(10)
    if letter.salutation:
        w.text(letter.salutation); w.gap(6)
    for paragraph in letter.paragraphs:
        w.text(paragraph); w.gap(8)

    w.gap(12)
    if letter.closing:
        w.text(letter.closing); w.gap(26)
    for k, line in enumerate(letter.signature):
        w.text(line, font=BODY_BOLD if k == 0 else BODY_FONT, color=INK if k == 0 else GREY)
    w.save()


def main() -> None:
    for stem in LETTERS:
        txt, pdf = DEMO_DIR / f"{stem}.txt", DEMO_DIR / f"{stem}.pdf"
        letter_to_pdf(txt, pdf)
        print(f"wrote {pdf.relative_to(DEMO_DIR.parent.parent)}")


if __name__ == "__main__":
    main()
