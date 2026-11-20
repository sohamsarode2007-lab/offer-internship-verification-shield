"""PDF forensic notes: parsed only, never executed, no values echoed, no score effect."""
import io
from datetime import datetime, timezone

from pypdf import PdfWriter

from app.services import plausibility
from app.services.pdf_forensics import pdf_flags, pdf_notes


def build(pages=((612, 792),), js=False, attach=False, created=None, modified=None, open_action=False):
    w = PdfWriter()
    for width, height in pages:
        w.add_blank_page(width, height)
    if js:
        from pypdf.generic import DictionaryObject, NameObject, TextStringObject
        action = DictionaryObject({
            NameObject("/S"): NameObject("/JavaScript"),
            NameObject("/JS"): TextStringObject("app.alert('x');"),
        })
        w._root_object[NameObject("/OpenAction")] = w._add_object(action)
    if attach:
        w.add_attachment("note.txt", b"hello")
    meta = {"/Producer": "Test Producer"}
    if created:
        meta["/CreationDate"] = created
    if modified:
        meta["/ModDate"] = modified
    w.add_metadata(meta)
    out = io.BytesIO(); w.write(out)
    return out.getvalue()


NOW = datetime(2026, 11, 19, tzinfo=timezone.utc)


def test_plain_pdf_has_no_flags():
    assert pdf_flags(build(), NOW) == []


def test_javascript_is_flagged_as_active_content():
    assert "active_content" in pdf_flags(build(js=True), NOW)


def test_embedded_file_is_flagged():
    assert "attachments" in pdf_flags(build(attach=True), NOW)


def test_modified_long_after_creation_is_flagged_but_same_day_is_not():
    assert "edited_later" in pdf_flags(build(created="D:20250101090000Z", modified="D:20250301090000Z"), NOW)
    assert pdf_flags(build(created="D:20250101090000Z", modified="D:20250101110000Z"), NOW) == []


def test_future_creation_date_is_flagged():
    assert "future_date" in pdf_flags(build(created="D:20301231000000Z"), NOW)


def test_mixed_page_sizes_are_flagged_but_equal_pages_are_not():
    assert "mixed_pages" in pdf_flags(build(pages=((612, 792), (400, 300))), NOW)
    assert "mixed_pages" not in pdf_flags(build(pages=((612, 792), (612, 792))), NOW)


def test_appended_edits_flagged_when_two_eof_markers():
    data = build()
    assert "appended_edits" in pdf_flags(data + b"\n%%EOF\n", NOW)


def test_non_pdf_and_empty_input_are_safe():
    assert pdf_flags(b"not a pdf") == [] and pdf_flags(None) == [] and pdf_flags(b"") == []
    assert pdf_flags(b"%PDF-1.4 garbage with no structure") == []


def test_notes_do_not_echo_metadata_and_flow_into_collect_notes():
    data = build(js=True, created="D:20250101090000Z", modified="D:20250401090000Z")
    notes = pdf_notes(data, NOW)
    assert notes and all("Test Producer" not in n and "2025" not in n for n in notes)
    assert any("active content" in n for n in plausibility.collect_notes("x", data))


def test_nothing_is_written_to_disk(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pdf_flags(build(js=True, attach=True), NOW)
    assert list(tmp_path.iterdir()) == []
