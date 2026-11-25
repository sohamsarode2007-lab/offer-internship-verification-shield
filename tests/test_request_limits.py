"""Body-size and concurrency limits, and email part/attachment limits."""
import threading

import pytest

from app.api import request_limits
from app.services import email_auth


def test_declared_oversized_body_is_refused_before_reading(api_client, monkeypatch):
    monkeypatch.setenv("MAX_REQUEST_BYTES", "2048")
    r = api_client.post("/analyze", data={"text": "x"}, headers={"content-length": "999999"})
    assert r.status_code == 413


def test_streamed_oversized_body_is_cut_off(api_client, monkeypatch):
    """No Content-Length (chunked): the bytes are counted as the form parser reads them."""
    monkeypatch.setenv("MAX_REQUEST_BYTES", "2048")

    def chunks():
        yield b'--B\r\nContent-Disposition: form-data; name="file"; filename="a.txt"\r\n\r\n'
        for _ in range(40):
            yield b"a" * 512
        yield b"\r\n--B--\r\n"

    r = api_client.post("/analyze", content=chunks(), headers={"content-type": "multipart/form-data; boundary=B"})
    assert r.status_code == 413


def test_normal_requests_pass_and_other_routes_have_a_small_cap(api_client):
    assert api_client.post("/analyze", data={"text": "A remote internship offer."}).status_code == 200
    r = api_client.post("/reports", content=b"x" * (300 * 1024), headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_busy_service_answers_503_not_a_queue(monkeypatch):
    monkeypatch.setattr(request_limits, "_slots", threading.BoundedSemaphore(1))
    monkeypatch.setenv("ANALYZE_QUEUE_SECONDS", "0")
    gen1 = request_limits.analyze_slot()
    next(gen1)                                   # takes the only slot
    gen2 = request_limits.analyze_slot()
    with pytest.raises(Exception) as err:
        next(gen2)
    assert getattr(err.value, "status_code", None) == 503 and err.value.headers["Retry-After"] == "30"
    gen1.close()                                  # slot is released
    gen3 = request_limits.analyze_slot()
    next(gen3)
    gen3.close()


def _eml(parts: int = 1, attach: int = 0, size: int = 10) -> bytes:
    from email.message import EmailMessage
    m = EmailMessage()
    m["From"] = "hr@acme.example"
    m.set_content("Hello")
    for i in range(attach):
        m.add_attachment(b"%PDF-" + b"0" * size, maintype="application", subtype="pdf", filename=f"a{i}.pdf")
    for i in range(parts - 1 - attach):
        m.add_attachment("x", subtype="plain")
    return m.as_bytes()


def test_email_with_too_many_parts_is_refused():
    with pytest.raises(ValueError, match="more than 60 parts"):
        email_auth.parse_eml(_eml(parts=80))


def test_email_keeps_at_most_five_attachments():
    assert len(email_auth.parse_eml(_eml(attach=9))["attachments"]) == 5


def test_oversized_attachment_is_refused():
    with pytest.raises(ValueError, match="larger than 10 MB"):
        email_auth.parse_eml(_eml(attach=1, size=11 * 1024 * 1024))
