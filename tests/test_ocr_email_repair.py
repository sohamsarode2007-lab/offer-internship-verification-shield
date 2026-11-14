"""OCR email repair: spaces OCR inserts around '@' are removed only for real email-shaped text.

Found by the OCR robustness test in CI run 43459252581: Tesseract read
"careers@quillmeresoftware.example" as "careers @quillmeresoftware.example" (and with a
space on both sides after JPEG compression), so no contact domain was extracted and the
Quillmere letter flipped from likely legitimate to manual review.
"""
import numpy as np
import pytest

from app.services import fact_extraction, ingestion


@pytest.mark.parametrize("ocr_text,expected", [
    ("replying to careers @quillmeresoftware.example.", "replying to careers@quillmeresoftware.example."),
    ("replying to careers @ quillmeresoftware.example.", "replying to careers@quillmeresoftware.example."),
    ("write to hr@ tarnwicklogistics.example", "write to hr@tarnwicklogistics.example"),
    ("contact talent\t@\thalvornfintech.example now", "contact talent@halvornfintech.example now"),
])
def test_split_email_is_rejoined(ocr_text, expected):
    assert ingestion.repair_ocr_emails(ocr_text) == expected


@pytest.mark.parametrize("text", [
    "careers@quillmeresoftware.example",          # already intact
    "Interview at 10 @ 5pm on Monday",            # right side is not a domain
    "Follow us @quillmere on social media",       # handle, no TLD
    "Pay to rky.verification@ybl now",            # UPI handle, no TLD: left untouched
    "Price: 3 @ Rs 500 each",
])
def test_non_email_text_is_unchanged(text):
    assert ingestion.repair_ocr_emails(text) == text


def test_repaired_ocr_text_yields_the_contact_domain(monkeypatch):
    monkeypatch.setattr(ingestion, "_run_ocr_engines",
                        lambda image, filename="document": "Please reply to careers @quillmeresoftware.example.")
    text = ingestion.run_ocr_on_image(np.zeros((4, 4, 3), dtype=np.uint8))
    facts = fact_extraction.extract_facts(text)
    assert facts["sender_domain"]["value"] == "quillmeresoftware.example"


def test_pasted_text_is_not_repaired():
    # Only OCR output is repaired; ingest_offer leaves typed/pasted text as written.
    text, _ = ingestion.ingest_offer(text="Contact careers @quillmeresoftware.example")
    assert "careers @quillmeresoftware.example" in text
