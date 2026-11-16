"""
Advisory scraper: reads employer recruitment-fraud pages and produces CANDIDATE advisory entries
for human review. Nothing it writes affects scoring until a person approves a candidate and runs
`promote`.

    ADVISORY_BOT_CONTACT=you@example.org python scripts/advisory_scraper.py fetch --out advisory_candidates.json
    # review the file: fill in "statement", set "approved": true
    python scripts/advisory_scraper.py promote advisory_candidates.json

Politeness and safety rules built in:
  - only https pages from scripts/advisory_sources.json (a human-vetted allowlist);
  - robots.txt is fetched and obeyed; if it cannot be read the source is skipped (fail closed);
  - identifies itself with a User-Agent that carries ADVISORY_BOT_CONTACT (required);
  - redirects to another host are refused; response size and time are capped; 2 s between sources;
  - personal data is dropped at extraction: phone numbers are removed and e-mail addresses keep
    only their domain; only a few short sentences are kept, with the source URL, as attribution.
Whether a site's terms allow automated reading is for a person to check before adding it to the
allowlist; this tool cannot decide that.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
SOURCES_FILE = Path(__file__).with_name("advisory_sources.json")
ADVISORIES_FILE = ROOT / "app" / "data" / "brand_advisories.json"
MAX_BYTES = 1_000_000
TIMEOUT_SECONDS = 10
DELAY_SECONDS = 2.0
MAX_STATEMENTS = 3
MAX_STATEMENT_CHARS = 220

_DOMAIN_RE = re.compile(r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
_PHONE_RE = re.compile(r"(?<![\w.])(?:\+\d{1,3}[\s-]?)?(?:\(?\d{2,5}\)?[\s-]?){2,4}\d{2,4}(?![\w.])")
_KEY_SENTENCE_RE = re.compile(
    r"\b(never|do(?:es)? not|don'?t|doesn'?t|no)\b.{0,60}\b(pay(?:ment)?|money|fees?|deposit|charges?)\b"
    r"|\b(gmail|yahoo|hotmail|free e-?mail|free mail)\b|\bonly\b.{0,80}@",
    re.IGNORECASE)


class _NoCrossHostRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects that leave the host that was asked for."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).hostname != urllib.parse.urlsplit(req.full_url).hostname:
            raise urllib.error.HTTPError(newurl, code, "cross-host redirect refused", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def user_agent() -> str:
    """User-Agent string carrying the operator's contact so site owners can reach them."""
    return f"OfferShieldAdvisoryBot/1.0 (+{os.environ['ADVISORY_BOT_CONTACT']})"


def _open(url: str) -> bytes:
    """Fetch a URL (size-capped, same-host redirects only). Separate so tests can replace it."""
    opener = urllib.request.build_opener(_NoCrossHostRedirect)
    request = urllib.request.Request(url, headers={"User-Agent": user_agent(), "Accept": "text/html,text/plain"})
    with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
        return response.read(MAX_BYTES)


class _TextExtractor(HTMLParser):
    """Visible text plus mailto: targets; script, style and similar are skipped."""

    _SKIP = {"script", "style", "noscript", "svg", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.chunks: list[str] = []
        self.mailtos: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1
        for name, value in attrs:
            if tag == "a" and name == "href" and value and value.lower().startswith("mailto:"):
                self.mailtos.append(value[7:].split("?")[0])
        if tag in {"p", "li", "br", "div", "h1", "h2", "h3", "h4", "tr"}:
            self.chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.chunks.append(data)


def page_text(html_source: str) -> tuple[str, list[str]]:
    """Return (visible text, mailto addresses) for an HTML page."""
    parser = _TextExtractor()
    parser.feed(html_source)
    return re.sub(r"[ \t\r\f\v]+", " ", "".join(parser.chunks)), parser.mailtos


def redact(text: str) -> str:
    """Drop phone numbers and keep only the domain of any e-mail address."""
    text = _EMAIL_RE.sub(lambda m: "@" + m.group(1).lower(), text)
    return _PHONE_RE.sub("[phone removed]", text)


def _registrable(host: str) -> str:
    from app.services.domain_verification import registrable_domain
    return registrable_domain(host)[0]


def own_domains(text: str, mailtos: list[str], page_host: str) -> list[str]:
    """E-mail domains on the page that belong to the page's own organisation (never free-mail domains)."""
    own = _registrable(page_host)
    found = {m.group(1).lower() for m in _EMAIL_RE.finditer(text)}
    found |= {a.split("@")[-1].lower() for a in mailtos if "@" in a}
    return sorted(d for d in found if _DOMAIN_RE.match(d) and (d == own or d.endswith("." + own)))


def key_statements(text: str) -> list[str]:
    """Up to a few short, redacted sentences about fees, free mail and official addresses."""
    kept: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        sentence = " ".join(sentence.split())
        if 20 <= len(sentence) <= 400 and _KEY_SENTENCE_RE.search(sentence):
            clean = redact(sentence)[:MAX_STATEMENT_CHARS]
            if clean not in kept:
                kept.append(clean)
        if len(kept) == MAX_STATEMENTS:
            break
    return kept


def _robots_allows(url: str) -> tuple[bool, str]:
    parts = urllib.parse.urlsplit(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    parser = urllib.robotparser.RobotFileParser()
    try:
        parser.parse(_open(robots_url).decode("utf-8", "replace").splitlines())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return True, "no robots.txt (404)"
        return False, f"robots.txt unreadable (HTTP {exc.code})"
    except Exception as exc:
        return False, f"robots.txt unreadable ({type(exc).__name__})"
    allowed = parser.can_fetch(user_agent(), url)
    return allowed, "allowed by robots.txt" if allowed else "disallowed by robots.txt"


def fetch_candidate(source: dict[str, Any], existing: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Read one allowlisted page and build a candidate entry, or return {"skipped": reason}."""
    url = source["url"]
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        return {"brand": source["brand"], "skipped": "only https URLs are read"}
    allowed, why = _robots_allows(url)
    if not allowed:
        return {"brand": source["brand"], "skipped": why}
    try:
        text, mailtos = page_text(_open(url).decode("utf-8", "replace"))
    except Exception as exc:
        return {"brand": source["brand"], "skipped": f"page unreadable ({type(exc).__name__})"}
    domains = own_domains(text, mailtos, parts.hostname)
    candidate: dict[str, Any] = {
        "brand": source["brand"], "aliases": source["aliases"], "official_domains": domains,
        "statement": "",  # a person writes this, from the suggested sentences, before approving
        "suggested_sentences": key_statements(text),
        "source": source["source"], "source_url": url,
        "retrieved": datetime.now(timezone.utc).date().isoformat(), "approved": False,
    }
    if existing:
        old = set(existing.get("official_domains", []))
        candidate["changes_vs_current"] = {"domains_added": sorted(set(domains) - old),
                                            "domains_missing_from_page": sorted(old - set(domains))}
    if not domains:
        candidate["warning"] = "no own-domain e-mail address found on the page; do not approve without checking it"
    return candidate


def validate_entry(entry: dict[str, Any]) -> list[str]:
    """Problems that block promoting an entry into app/data/brand_advisories.json."""
    problems = []
    if not isinstance(entry.get("brand"), str) or not entry["brand"].strip():
        problems.append("brand is missing")
    aliases = entry.get("aliases")
    if not (isinstance(aliases, list) and aliases and all(isinstance(a, str) and a.strip() for a in aliases)):
        problems.append("aliases must be a non-empty list of names")
    domains = entry.get("official_domains")
    if not (isinstance(domains, list) and domains and all(isinstance(d, str) and _DOMAIN_RE.match(d) for d in domains)):
        problems.append("official_domains must be a non-empty list of valid domains")
    statement = entry.get("statement")
    if not (isinstance(statement, str) and 10 <= len(statement.strip()) <= 300) or "@" in statement:
        problems.append("statement must be 10-300 characters, written by a person, with no e-mail address")
    if not str(entry.get("source_url", "")).startswith("https://") or not entry.get("source"):
        problems.append("source and an https source_url are required")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(entry.get("retrieved", ""))):
        problems.append("retrieved must be a YYYY-MM-DD date")
    return problems


def promote(candidates_path: Path) -> int:
    """Merge approved, valid candidates into the advisories file. All-or-nothing."""
    candidates = json.loads(candidates_path.read_text(encoding="utf-8"))["candidates"]
    approved = [c for c in candidates if c.get("approved") is True]
    failures = {c.get("brand", "?"): validate_entry(c) for c in approved if validate_entry(c)}
    if failures:
        for brand, problems in failures.items():
            print(f"NOT PROMOTED {brand}: " + "; ".join(problems), file=sys.stderr)
        return 1
    data = json.loads(ADVISORIES_FILE.read_text(encoding="utf-8"))
    by_brand = {a["brand"]: a for a in data["advisories"]}
    for c in approved:
        by_brand[c["brand"]] = {k: c[k] for k in
                                ("brand", "aliases", "official_domains", "statement", "source", "source_url", "retrieved")}
    data["advisories"] = list(by_brand.values())
    temp = ADVISORIES_FILE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(ADVISORIES_FILE)
    print(f"Promoted {len(approved)} advisory entr{'y' if len(approved) == 1 else 'ies'}. Review the diff, then commit.")
    return 0


def run_fetch(out: Path, sources_path: Path = SOURCES_FILE, delay: float = DELAY_SECONDS) -> int:
    """Fetch every allowlisted source and write the candidates file."""
    if not os.environ.get("ADVISORY_BOT_CONTACT", "").strip():
        print("Set ADVISORY_BOT_CONTACT (an e-mail or URL) so site owners can reach you.", file=sys.stderr)
        return 2
    sources = json.loads(sources_path.read_text(encoding="utf-8"))["sources"]
    current = {a["brand"]: a for a in json.loads(ADVISORIES_FILE.read_text(encoding="utf-8"))["advisories"]}
    results = []
    for i, source in enumerate(sources):
        if i:
            time.sleep(delay)
        results.append(fetch_candidate(source, current.get(source["brand"])))
    out.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                               "candidates": results}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    skipped = [r for r in results if "skipped" in r]
    print(f"{len(results) - len(skipped)} candidate(s) written to {out}; {len(skipped)} skipped.")
    for r in skipped:
        print(f"  skipped {r['brand']}: {r['skipped']}", file=sys.stderr)
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch", help="read the allowlisted pages and write candidates")
    fetch.add_argument("--out", type=Path, default=Path("advisory_candidates.json"))
    promote_cmd = sub.add_parser("promote", help="merge approved candidates into app/data/brand_advisories.json")
    promote_cmd.add_argument("candidates", type=Path)
    args = parser.parse_args(argv)
    return run_fetch(args.out) if args.command == "fetch" else promote(args.candidates)


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
