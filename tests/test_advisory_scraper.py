"""Advisory scraper: offline tests only. The employer is fictional and lives on the reserved .example TLD."""
import json
import urllib.request
import urllib.error

import pytest

from scripts import advisory_scraper as scraper

URL = "https://careers.brightwave.example/fraud-alert"
SOURCE = {"brand": "Brightwave", "aliases": ["brightwave", "brightwave systems"],
          "source": "Brightwave recruitment fraud alert", "url": URL}
PAGE = """<html><head><style>.x{color:red}</style><script>var a="Never pay money @evil.example";</script></head>
<body><h1>Recruitment fraud alert</h1>
<p>Brightwave never asks candidates for a fee or a security deposit. Call +91 98765 43210 to report.</p>
<p>Genuine mail comes only from addresses at @brightwave.example, not from gmail or yahoo accounts.</p>
<p>Write to <a href="mailto:talent@brightwave.example?subject=x">our team</a> or priya.sharma@brightwave.example.</p>
<p>Unrelated partner: help@partner-site.example.</p></body></html>"""
ROBOTS_OK = "User-agent: *\nAllow: /\n"


@pytest.fixture(autouse=True)
def contact(monkeypatch):
    monkeypatch.setenv("ADVISORY_BOT_CONTACT", "maintainer@contact.example")


@pytest.fixture
def web(monkeypatch):
    """Replace the network. pages maps URL -> bytes or an exception; every requested URL is recorded."""
    pages = {"https://careers.brightwave.example/robots.txt": ROBOTS_OK.encode(), URL: PAGE.encode()}
    calls = []

    def fake_open(url):
        calls.append(url)
        result = pages[url]
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr(scraper, "_open", fake_open)
    fake_open.pages, fake_open.calls = pages, calls
    web = type("Web", (), {})()
    web.pages, web.calls = pages, calls
    return web


def test_extracts_only_own_domain_and_ignores_script_text(web):
    candidate = scraper.fetch_candidate(SOURCE)
    assert candidate["official_domains"] == ["brightwave.example"]
    assert candidate["approved"] is False
    assert candidate["statement"] == ""
    assert candidate["source_url"] == URL
    assert "warning" not in candidate


def test_phone_numbers_and_email_local_parts_never_reach_the_output(web):
    candidate = scraper.fetch_candidate(SOURCE)
    blob = json.dumps(candidate)
    for leaked in ("98765", "43210", "priya.sharma", "talent@", "@evil.example"):
        assert leaked not in blob
    assert candidate["suggested_sentences"], "fee/free-mail sentences should be suggested"
    assert len(candidate["suggested_sentences"]) <= scraper.MAX_STATEMENTS
    assert all(len(s) <= scraper.MAX_STATEMENT_CHARS for s in candidate["suggested_sentences"])


def test_redact_keeps_only_email_domain_and_removes_phone():
    assert scraper.redact("mail jo.doe@Firm.example now") == "mail @firm.example now"
    assert "[phone removed]" in scraper.redact("call +91 98765 43210 today")


def test_page_without_own_domain_gets_a_warning(web):
    web.pages[URL] = b"<p>We never ask for a fee or deposit.</p><p>Write to help@partner-site.example</p>"
    candidate = scraper.fetch_candidate(SOURCE)
    assert candidate["official_domains"] == []
    assert "do not approve" in candidate["warning"]


def test_robots_disallow_means_page_is_never_fetched(web):
    web.pages["https://careers.brightwave.example/robots.txt"] = b"User-agent: *\nDisallow: /\n"
    result = scraper.fetch_candidate(SOURCE)
    assert result["skipped"] == "disallowed by robots.txt"
    assert URL not in web.calls


@pytest.mark.parametrize("failure", [urllib.error.HTTPError("u", 500, "err", {}, None), OSError("down"), TimeoutError()])
def test_unreadable_robots_fails_closed(web, failure):
    web.pages["https://careers.brightwave.example/robots.txt"] = failure
    result = scraper.fetch_candidate(SOURCE)
    assert "robots.txt unreadable" in result["skipped"]
    assert URL not in web.calls


def test_missing_robots_file_404_is_allowed(web):
    web.pages["https://careers.brightwave.example/robots.txt"] = urllib.error.HTTPError("u", 404, "nf", {}, None)
    assert "skipped" not in scraper.fetch_candidate(SOURCE)


def test_page_failure_is_reported_not_raised(web):
    web.pages[URL] = OSError("reset")
    assert scraper.fetch_candidate(SOURCE)["skipped"].startswith("page unreadable")


def test_non_https_source_is_refused_without_any_request(web):
    result = scraper.fetch_candidate({**SOURCE, "url": "http://careers.brightwave.example/fraud-alert"})
    assert "https" in result["skipped"]
    assert web.calls == []


def test_cross_host_redirect_is_refused():
    handler = scraper._NoCrossHostRedirect()
    request = urllib.request.Request("https://careers.brightwave.example/a")
    with pytest.raises(urllib.error.HTTPError):
        handler.redirect_request(request, None, 302, "Found", {}, "https://elsewhere.example/b")
    same = handler.redirect_request(request, None, 302, "Found", {}, "https://careers.brightwave.example/b")
    assert same is not None


def test_user_agent_carries_contact(monkeypatch):
    assert "maintainer@contact.example" in scraper.user_agent()


def test_changes_vs_current_reports_domain_differences(web):
    existing = {"official_domains": ["brightwave.example", "old-brightwave.example"]}
    changes = scraper.fetch_candidate(SOURCE, existing)["changes_vs_current"]
    assert changes == {"domains_added": [], "domains_missing_from_page": ["old-brightwave.example"]}


def test_fetch_requires_contact_and_makes_no_request(monkeypatch, web, tmp_path):
    monkeypatch.delenv("ADVISORY_BOT_CONTACT")
    assert scraper.run_fetch(tmp_path / "out.json") == 2
    assert web.calls == []


def test_run_fetch_writes_candidates_file(monkeypatch, web, tmp_path):
    sources = tmp_path / "sources.json"
    sources.write_text(json.dumps({"sources": [SOURCE]}))
    advisories = tmp_path / "adv.json"
    advisories.write_text(json.dumps({"advisories": []}))
    monkeypatch.setattr(scraper, "ADVISORIES_FILE", advisories)
    out = tmp_path / "out.json"
    assert scraper.run_fetch(out, sources_path=sources, delay=0) == 0
    written = json.loads(out.read_text())["candidates"]
    assert written[0]["brand"] == "Brightwave" and written[0]["approved"] is False


def good(**overrides):
    entry = {"brand": "Brightwave", "aliases": ["brightwave"], "official_domains": ["brightwave.example"],
             "statement": "says it never asks candidates for a fee or a deposit", "source": "Brightwave alert",
             "source_url": URL, "retrieved": "2026-11-16", "approved": True}
    entry.update(overrides)
    return entry


@pytest.fixture
def advisories(monkeypatch, tmp_path):
    path = tmp_path / "brand_advisories.json"
    path.write_text(json.dumps({"advisories": [{"brand": "Other", "aliases": ["other"]}]}))
    monkeypatch.setattr(scraper, "ADVISORIES_FILE", path)
    return path


def write_candidates(tmp_path, *entries):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"candidates": list(entries)}))
    return path


def test_promote_merges_only_approved_valid_entries(advisories, tmp_path):
    unapproved = good(brand="Unapproved", approved=False)
    path = write_candidates(tmp_path, good(), unapproved)
    assert scraper.promote(path) == 0
    brands = [a["brand"] for a in json.loads(advisories.read_text())["advisories"]]
    assert brands == ["Other", "Brightwave"]
    merged = json.loads(advisories.read_text())["advisories"][1]
    assert "approved" not in merged and "suggested_sentences" not in merged


def test_promote_is_all_or_nothing(advisories, tmp_path):
    before = advisories.read_text()
    path = write_candidates(tmp_path, good(), good(brand="Broken", statement=""))
    assert scraper.promote(path) == 1
    assert advisories.read_text() == before


@pytest.mark.parametrize("override", [
    {"statement": ""}, {"statement": "write to hr@brightwave.example for this"}, {"official_domains": []},
    {"official_domains": ["not a domain"]}, {"aliases": []}, {"source_url": "http://x.example/a"},
    {"retrieved": "yesterday"}, {"brand": " "},
])
def test_validate_entry_rejects_bad_entries(override):
    assert scraper.validate_entry(good(**override))


def test_validate_entry_accepts_a_good_entry():
    assert scraper.validate_entry(good()) == []


def test_unapproved_candidates_alone_change_nothing(advisories, tmp_path):
    before = advisories.read_text()
    assert scraper.promote(write_candidates(tmp_path, good(approved=False))) == 0
    assert json.loads(advisories.read_text()) == json.loads(before)
