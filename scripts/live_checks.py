"""Run the outbound features against the real services ONCE, on your machine, and print PASS / FAIL / SKIP.

The test suite mocks DNS, WHOIS and HTTP, so none of this has been exercised against the real internet. Run it
before relying on these features. It sends only fixed test addresses (plus a CIN taken from the registry's own
first row), never offer text, and never prints API keys.

    python -m scripts.live_checks                      # all checks that have what they need
    python -m scripts.live_checks --careers-domain example-company.in   # a domain YOU know has a careers page

Keys, set only for the run: DATA_GOV_IN_API_KEY, WEB_RISK_API_KEY. A check without its key is SKIPPED, not passed.
Paste the whole output back when something FAILs; see docs/LIVE_CHECKS.md for what each result means.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from app.services import careers_page, link_lookup, ogd_registry, safe_fetch

REQUIRED_FIELDS = {"CIN", "CompanyName", "CompanyStatus"}
WEB_RISK_TEST_URL = "http://testsafebrowsing.appspot.com/s/malware.html"   # Google's documented test page
results: list[tuple[str, str, str]] = []


def record(status: str, name: str, note: str) -> None:
    results.append((status, name, note))
    print(f"[{status}] {name}: {note}", flush=True)


def check_ogd() -> None:
    name = "data.gov.in company master"
    if not ogd_registry.is_enabled():
        return record("SKIP", name, "DATA_GOV_IN_API_KEY is not set")
    query = urllib.parse.urlencode({"api-key": os.environ["DATA_GOV_IN_API_KEY"].strip(), "format": "json", "limit": "1"})
    try:
        payload = json.loads(ogd_registry._open(f"{ogd_registry.resource_url()}?{query}"))
    except urllib.error.HTTPError as exc:
        return record("FAIL", name, f"HTTP {exc.code} from {urllib.parse.urlsplit(ogd_registry.resource_url()).netloc} "
                                    "(401/403: key or terms; 404: host or resource id moved; 429: rate limit)")
    except Exception as exc:
        return record("FAIL", name, f"could not reach {urllib.parse.urlsplit(ogd_registry.resource_url()).netloc}: "
                                    f"{type(exc).__name__}")
    rows = payload.get("records") if isinstance(payload, dict) else None
    if not rows or not isinstance(rows[0], dict):
        return record("FAIL", name, f"answered but no records; top-level keys: {sorted(payload)[:8] if isinstance(payload, dict) else type(payload).__name__}")
    missing = REQUIRED_FIELDS - set(rows[0])
    if missing:
        return record("FAIL", name, f"field names changed; missing {sorted(missing)}, got {sorted(rows[0])[:10]}")
    record("PASS", name + " (host, key, field names)", f"fields present: {sorted(REQUIRED_FIELDS)}")
    cin = str(rows[0]["CIN"]).strip()
    status, company = ogd_registry.fetch_company_by_cin(cin)
    if status == "found" and company:
        record("PASS", "data.gov.in filters[CIN]", "a lookup by that row's own CIN returned the same company")
    else:
        record("FAIL", "data.gov.in filters[CIN]", f"lookup by an existing CIN gave '{status}'; the filter may not work")


def check_web_risk() -> None:
    name = "Google Web Risk"
    key = os.getenv("WEB_RISK_API_KEY", "")
    if not key:
        return record("SKIP", name, "WEB_RISK_API_KEY is not set")
    for label, url, expect_listed in (("test threat page", WEB_RISK_TEST_URL, True), ("harmless page", "https://example.com/", False)):
        query = urllib.parse.urlencode([("threatTypes", t) for t in link_lookup.THREAT_TYPES] + [("uri", url), ("key", key)])
        try:
            data = link_lookup._get_json(f"{link_lookup.WEB_RISK_URL}?{query}")
        except urllib.error.HTTPError as exc:
            return record("FAIL", name, f"HTTP {exc.code} (400: bad request; 403: API not enabled or key restricted; 429: quota)")
        except Exception as exc:
            return record("FAIL", name, f"could not reach the API: {type(exc).__name__}")
        listed = bool((data.get("threat") or {}).get("threatTypes"))
        if listed == expect_listed:
            record("PASS", f"{name}: {label}", "threat-listed" if listed else "not listed (reported as 'unknown' by the app)")
        else:
            record("FAIL", f"{name}: {label}", f"expected {'listed' if expect_listed else 'not listed'}; if the test page is "
                   "not listed Google may have changed it, so confirm with Google's current Web Risk test URL before worrying")


def check_redirects_and_tls() -> None:
    name = "redirect and TLS handling"
    os.environ.setdefault("LINK_LOOKUPS", "1")
    cases = (("http to https redirect", "http://github.com", lambda v: v["tls"] == "valid" and v["landing_host"] in (None, "github.com", "www.github.com")),
             ("expired certificate", "https://expired.badssl.com/", lambda v: v["tls"] == "invalid"),
             ("wrong-host certificate", "https://wrong.host.badssl.com/", lambda v: v["tls"] == "invalid"))
    for label, url, ok in cases:
        try:
            visit = link_lookup.follow(url)
        except Exception as exc:
            record("FAIL", f"{name}: {label}", f"raised {type(exc).__name__}")
            continue
        detail = f"tls={visit['tls']} hops={visit['hops']} stopped={visit['stopped']}"
        if visit["stopped"]:
            detail += " (the lookup stopped before a verdict: network blocked, deadline, or address refused; not a TLS result)"
        record("PASS" if ok(visit) else "FAIL", f"{name}: {label}", detail)
    try:
        safe_fetch.public_addresses("localhost")
        record("FAIL", "private address refused", "localhost was accepted")
    except safe_fetch.UnsafeTarget:
        record("PASS", "private address refused", "localhost is refused before any connection")


def check_careers(domain: str | None) -> None:
    name = "careers page lookup"
    if not domain:
        return record("SKIP", name, "pass --careers-domain <a domain you know has a careers page>")
    os.environ["CAREERS_PAGE_LOOKUPS"] = "1"
    found = careers_page.careers_page_found(domain)
    record("PASS" if found else "FAIL", name, f"{'found' if found else 'did not find'} a careers page on {domain}"
           + ("" if found else " (the site may block automated requests or use an unusual path; that is expected sometimes)"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--careers-domain")
    args = parser.parse_args()
    check_ogd(); check_web_risk(); check_redirects_and_tls(); check_careers(args.careers_domain)
    failed = sum(1 for s, _, _ in results if s == "FAIL")
    print(f"\n{sum(1 for s, _, _ in results if s == 'PASS')} passed, {failed} failed, "
          f"{sum(1 for s, _, _ in results if s == 'SKIP')} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
