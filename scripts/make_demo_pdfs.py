"""
Generate plain A4 PDFs from fixtures/demo/*.txt (line breaks preserved).

Usage (from the project root):
    .\\.venv\\Scripts\\python.exe scripts\\make_demo_pdfs.py

Requires reportlab (requirements-dev.txt).
"""
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas

DEMO_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "demo"
FONT, SIZE, LEADING, MARGIN = "Helvetica", 10, 14, 50


def text_to_pdf(txt_path: Path, pdf_path: Path) -> None:
    width, height = A4
    c = canvas.Canvas(str(pdf_path), pagesize=A4, invariant=1)  # invariant: reproducible bytes
    c.setTitle(txt_path.stem)
    c.setFont(FONT, SIZE)
    y = height - MARGIN
    for line in txt_path.read_text(encoding="utf-8").splitlines():
        # Wrap only if a line is wider than the page; source line breaks are always kept.
        for part in simpleSplit(line, FONT, SIZE, width - 2 * MARGIN) or [""]:
            if y < MARGIN:
                c.showPage()
                c.setFont(FONT, SIZE)
                y = height - MARGIN
            c.drawString(MARGIN, y, part)
            y -= LEADING
    c.save()


if __name__ == "__main__":
    for txt in sorted(DEMO_DIR.glob("*.txt")):
        pdf = txt.with_suffix(".pdf")
        text_to_pdf(txt, pdf)
        print(f"wrote {pdf.relative_to(DEMO_DIR.parent.parent)}")
