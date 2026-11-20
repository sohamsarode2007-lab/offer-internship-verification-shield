"""
Link patterns (informational only: never change the score, never touch the network)

Looks at the links written in an offer and notes structural tricks, from the text alone:

  shortener   the link uses a known URL shortener (the real destination is hidden)
  punycode    an "xn--" host label (an internationalised name, often used for lookalikes)
  homoglyph   a host that mixes alphabets (for example Latin and Cyrillic letters)
  ip_literal  the host is a raw IP address
  userinfo    "name@host" inside the link, which makes the start look like a trusted site

Each is a weak signal with innocent explanations (shorteners are common), so a note is shown in 'Why'
with no score impact. This module fetches nothing: redirects and reputation lookups live in link_lookup.py and are
opt-in with consent (see docs/JUDGMENT_CALLS.md). Notes never repeat the link or its domain. Nothing here is stored.
"""
import ipaddress
import re
import unicodedata
from typing import List
from urllib.parse import urlsplit

_URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"'\])}]+", re.I)
SHORTENERS = frozenset({
    "bit.ly", "tinyurl.com", "t.co", "goo.gl", "rb.gy", "cutt.ly", "is.gd", "shorturl.at", "tiny.cc",
    "ow.ly", "buff.ly", "rebrand.ly", "bl.ink", "s.id", "v.gd", "t.ly",
})

NOTES = {
    "shortener": "A link in the offer uses a link shortener, so its real destination is hidden. Do not open it until you know who sent it.",
    "punycode": "A link in the offer uses an internationalised (xn--) domain, a trick sometimes used to imitate another site.",
    "homoglyph": "A link in the offer mixes alphabets that look alike, which can imitate a real company's domain.",
    "ip_literal": "A link in the offer points to a raw IP address instead of a company website.",
    "userinfo": "A link in the offer has an '@' in it, so what looks like the site name is not the real destination.",
}


def _scripts(label: str) -> set:
    out = set()
    for ch in label:
        if ch.isalpha():
            name = unicodedata.name(ch, "")
            out.add(name.split(" ")[0] if name else "UNKNOWN")
    return out


def url_flags(text: str) -> List[str]:
    """Pattern ids found across all links in the text (each id at most once, fixed order)."""
    found = set()
    for match in _URL_RE.finditer(text or ""):
        raw = match.group(0).rstrip(".,;:!?")
        if not raw.lower().startswith("http"):
            raw = "http://" + raw
        try:
            parts = urlsplit(raw)
            host = (parts.hostname or "").lower()
        except ValueError:
            continue
        if not host:
            continue
        if "@" in parts.netloc:
            found.add("userinfo")
        try:
            ipaddress.ip_address(host.strip("[]"))
            found.add("ip_literal")
            continue
        except ValueError:
            pass
        if host in SHORTENERS or any(host.endswith("." + s) for s in SHORTENERS):
            found.add("shortener")
        if any(label.startswith("xn--") for label in host.split(".")):
            found.add("punycode")
        if any(len(_scripts(label)) > 1 for label in host.split(".")):
            found.add("homoglyph")
    order = ["shortener", "punycode", "homoglyph", "ip_literal", "userinfo"]
    return [f for f in order if f in found]


def url_notes(text: str) -> List[str]:
    return [NOTES[f] for f in url_flags(text)]
