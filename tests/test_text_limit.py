"""The 50,000-character cap applies to text extracted from files and to combined parts, not only pasted text."""
from app.api.routes.analyze import MAX_TEXT_CHARS

OK_LINE = "Interview details will follow by email. "


def _txt(n):
    return (OK_LINE * (n // len(OK_LINE) + 1))[:n].encode()


def test_oversized_text_file_is_rejected(api_client):
    r = api_client.post("/analyze", files={"file": ("offer.txt", _txt(MAX_TEXT_CHARS + 1000), "text/plain")})
    assert r.status_code == 413 and "longer than" in r.json()["detail"]


def test_file_at_the_limit_is_accepted(api_client):
    r = api_client.post("/analyze", files={"file": ("offer.txt", _txt(MAX_TEXT_CHARS - 10), "text/plain")})
    assert r.status_code == 200


def test_pasted_text_plus_file_over_the_limit_is_rejected(api_client):
    r = api_client.post("/analyze", data={"text": OK_LINE * 400},
                        files={"file": ("offer.txt", _txt(MAX_TEXT_CHARS - 100), "text/plain")})
    assert r.status_code == 413
