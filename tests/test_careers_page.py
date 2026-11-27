"""Careers-page note: off by default, informational only, fails closed. No real network."""
import pytest

from app.services import careers_page as cp


def test_off_by_default(monkeypatch):
    monkeypatch.delenv("CAREERS_PAGE_LOOKUPS", raising=False)
    monkeypatch.setattr(cp, "_open", lambda url: pytest.fail("must not fetch"))
    assert cp.careers_page_found("quillmere.example") is False


def test_found_when_page_reads_like_careers(monkeypatch):
    monkeypatch.setenv("CAREERS_PAGE_LOOKUPS", "1")
    monkeypatch.setattr(cp, "_open", lambda url: b"<h1>Careers</h1> open positions")
    assert cp.careers_page_found("quillmere.example") is True


def test_not_found_when_page_is_unrelated(monkeypatch):
    monkeypatch.setenv("CAREERS_PAGE_LOOKUPS", "1")
    monkeypatch.setattr(cp, "_open", lambda url: b"<h1>Welcome</h1> our shop")
    assert cp.careers_page_found("quillmere.example") is False


def test_errors_and_redirects_fail_closed(monkeypatch):
    monkeypatch.setenv("CAREERS_PAGE_LOOKUPS", "1")
    def boom(url):
        raise OSError("down")
    monkeypatch.setattr(cp, "_open", boom)
    assert cp.careers_page_found("quillmere.example") is False


def test_non_public_address_is_never_contacted(monkeypatch):
    """The real _open runs; the pinned client refuses before any connection is made."""
    from app.services import safe_fetch
    monkeypatch.setenv("CAREERS_PAGE_LOOKUPS", "1")
    monkeypatch.setattr(safe_fetch.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("10.0.0.5", 443))])
    monkeypatch.setattr(safe_fetch, "_connect", lambda *a, **k: pytest.fail("must not connect"))
    assert cp.careers_page_found("internal.example") is False
