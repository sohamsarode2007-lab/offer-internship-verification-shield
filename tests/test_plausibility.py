"""Plausibility notes are informational: they appear in 'Why' with no score impact."""
import io

import pytest
from pypdf import PdfWriter

from app.services import plausibility as pl


def pdf(producer="", creator=""):
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    meta = {}
    if producer:
        meta["/Producer"] = producer
    if creator:
        meta["/Creator"] = creator
    if meta:
        writer.add_metadata(meta)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.mark.parametrize("text", [
    "Internship stipend: Rs. 1,50,000 per month.",
    "Fresher salary Rs 4,000 per day.",
    "Entry level package 35 LPA.",
])
def test_unusual_pay_for_fresher_roles_is_noted(text):
    assert pl.salary_note(text)


@pytest.mark.parametrize("text", [
    "Internship stipend: Rs 8,000 per month.",
    "Senior architect salary Rs 1,50,000 per month.",
    "Fresher package 6 LPA.",
    "Trainee stipend Rs 2,000 per day.",
])
def test_ordinary_or_non_fresher_pay_is_not_noted(text):
    assert pl.salary_note(text) is None


@pytest.mark.parametrize("text", ["Call +91 12345 67890", "Call +91 98765 4321", "WhatsApp +1 415 555 0132"])
def test_odd_phone_numbers_are_noted(text):
    assert pl.phone_note(text)


@pytest.mark.parametrize("text", ["Call +91 98765 43210", "Call 98765 43210", "No number here"])
def test_normal_indian_mobile_is_not_noted(text):
    assert pl.phone_note(text) is None


def test_online_editor_in_pdf_metadata_is_noted_without_naming_values():
    note = pl.pdf_metadata_note(pdf(producer="Canva"))
    assert note and "Canva" not in note


@pytest.mark.parametrize("data", [pdf(producer="Microsoft Word"), pdf(), b"not a pdf", None])
def test_other_or_unreadable_pdfs_give_no_note(data):
    assert pl.pdf_metadata_note(data) is None


def test_notes_never_repeat_the_amount_or_number():
    notes = " ".join(pl.collect_notes("Intern stipend Rs 2,50,000 per month. Call +91 12345 67890"))
    assert "2,50,000" not in notes and "12345" not in notes


BASE = "You are selected as an intern. Rate products and earn commission. Contact HR on Telegram. "


def test_notes_do_not_change_the_score(api_client):
    plain = api_client.post("/analyze", data={"text": BASE + "Call +91 98765 43210"}).json()
    odd = api_client.post("/analyze", data={"text": BASE + "Call +91 12345 67890"}).json()
    assert plain["overall_risk_score"] == odd["overall_risk_score"]
    notes = [r for r in odd["reasons"] if r["impact"] is None]
    assert any("Indian mobile" in r["text"] for r in notes)
    assert not [r for r in plain["reasons"] if r["impact"] is None]


def test_pdf_upload_note_reaches_the_result(api_client, monkeypatch):
    from app.services import ingestion
    monkeypatch.setattr(ingestion, "_extract_pdf_text", lambda data, doc: "Intern offer. Rate products and earn commission.")
    body = api_client.post("/analyze", files={"file": ("offer.pdf", pdf(producer="Canva"), "application/pdf")}).json()
    assert any("online design or editing tool" in r["text"] for r in body["reasons"])
