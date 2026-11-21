"""
Employer-published recruitment-fraud statements (app/data/brand_advisories.json).

Each entry records what an employer's own fraud page says about the domain it recruits
from, with the source URL and the date it was read. When an offer names one of these
employers but the sender's domain is not that employer's recruitment domain, the domain
check fails with wording attributed to the source ("TCS says ..."), never as our own
verdict about the sender.

Only employers whose page was actually opened and read are listed. The list is small
on purpose: a missing employer is simply not checked.
"""
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional, TypedDict

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "brand_advisories.json"


class Advisory(TypedDict):
    brand: str
    aliases: list[str]
    official_domains: list[str]
    statement: str
    source: str
    source_url: str
    retrieved: str


@lru_cache(maxsize=1)
def load_advisories() -> tuple[Advisory, ...]:
    """Parse the data file once; a missing or malformed file means no advisories (fail open for the check)."""
    try:
        return tuple(json.loads(DATA_FILE.read_text(encoding="utf-8"))["advisories"])
    except (OSError, ValueError, KeyError, TypeError):
        return ()


def _words(value: str) -> str:
    return " " + re.sub(r"[^a-z0-9]+", " ", value.lower()).strip() + " "


def find_advisory(company_name: Optional[str]) -> Optional[Advisory]:
    """Advisory whose brand alias appears as whole words in the claimed company name."""
    if not company_name:
        return None
    haystack = _words(company_name)
    for advisory in load_advisories():
        if any(_words(alias) in haystack for alias in advisory["aliases"]):
            return advisory
    return None


def official_domain_mismatch(company_name: Optional[str], registrable: str) -> Optional[str]:
    """Attributed explanation if the named employer has an advisory and `registrable` is not its domain."""
    advisory = find_advisory(company_name)
    if not advisory:
        return None
    host = registrable.lower().rstrip(".")
    if any(host == d or host.endswith("." + d) for d in advisory["official_domains"]):
        return None
    official = ", ".join(advisory["official_domains"])
    return (f"The letter names {advisory['brand']}, but the sender domain '{host}' is not its official "
            f"recruitment domain ({official}). Per {advisory['source']} ({advisory['source_url']}, "
            f"read {advisory['retrieved']}), {advisory['brand']} {advisory['statement']}")
