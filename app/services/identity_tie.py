"""
Does the contact domain belong to the company the registry found?

A company number can be copied from the public register onto any offer, so a registry match alone says the
company exists, not that this sender works for it. For the "likely legitimate" band the sender's domain must
also be recognisably the registered company's name. This is a deliberately strict, conservative test:

  - the domain's main label equals the whole company name (legal words removed), e.g. emberlakeanalytics.example
    for "Emberlake Analytics Pvt. Ltd.";
  - or it equals the name's first distinctive word, e.g. infosys.example for "Infosys Limited"; or
  - it equals the initials of a name with 3+ words, e.g. tcs for "Tata Consultancy Services".

Anything else (hcltech for "HCL Technologies", careers pages on other domains, a name plus extra words) is
"not tied", which only means "verify manually". It is not proof of anything: a scammer can register a domain that
passes this test, which is why EC41-style lookalikes remain a documented limit.
"""
import re
from typing import Optional

from app.services.domain_verification import registrable_domain

LEGAL_WORDS = {"private", "pvt", "limited", "ltd", "llp", "inc", "opc", "india", "company", "co", "corporation", "corp"}


def _tokens(name: str) -> list:
    words = re.findall(r"[a-z0-9]+", (name or "").lower())
    return [w for w in words if w not in LEGAL_WORDS]


def domain_tied_to_company(domain: Optional[str], company_name: Optional[str]) -> bool:
    if not domain or not company_name:
        return False
    label = re.sub(r"[^a-z0-9]", "", registrable_domain(domain.strip().lower())[1])
    tokens = _tokens(company_name)
    if len(label) < 3 or not tokens:
        return False
    if label == "".join(tokens):
        return True
    if len(tokens[0]) >= 4 and label == tokens[0]:
        return True
    return len(tokens) >= 3 and len(label) >= 3 and label == "".join(t[0] for t in tokens)
