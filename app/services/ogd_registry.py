"""
Live company-master lookup by CIN against the data.gov.in Open Government Data API.

Resource: "Registrars of Companies (RoC)-wise Company Master Data" (Ministry of Corporate
Affairs, published under the Government Open Data License - India). It is a periodically
refreshed snapshot, not a live registry: a company can change status after the snapshot.

Design rules:
  - Opt-in: runs only when DATA_GOV_IN_API_KEY is set. The shared public sample key is
    never used (it returns at most 10 rows and is rate-limited for everyone).
  - Fail closed: any network error, timeout, bad JSON or unexpected payload returns
    "unavailable". The caller must treat that as "registry not checked", never as
    "company not found" (which would wrongly look like evidence against the company).
  - The API key travels in the query string, so URLs and exception messages are never logged.
  - Fixed host and a strictly validated CIN: no user-controlled URL parts.
"""
import json
import logging
import os
import re
import urllib.parse
import urllib.request
from typing import Optional, TypedDict

logger = logging.getLogger(__name__)

OGD_RESOURCE_URL = "https://api.data.gov.in/resource/4dbe5667-7b6b-41d7-82af-211562424d9a"
TIMEOUT_SECONDS = 2.5
MAX_RESPONSE_BYTES = 256 * 1024
CIN_RE = re.compile(r"^[LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}$")

FOUND, NOT_FOUND, UNAVAILABLE = "found", "not_found", "unavailable"


class OgdCompany(TypedDict):
    """The only fields kept from the API row (no address, capital or industry data)."""
    cin: str
    company_name: str
    company_status: str
    date_of_registration: Optional[str]


def is_enabled() -> bool:
    """True when a personal data.gov.in API key is configured."""
    return bool(os.getenv("DATA_GOV_IN_API_KEY", "").strip())


def _open(url: str) -> bytes:
    """Fetch the URL body (size-capped). Separate function so tests can replace it."""
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 (fixed https host)
        return response.read(MAX_RESPONSE_BYTES)


def fetch_company_by_cin(cin: str) -> tuple[str, Optional[OgdCompany]]:
    """
    Look up one CIN. Returns (status, record): status is "found", "not_found" or
    "unavailable". "not_found" means the API answered with zero rows for this CIN.
    """
    cin = (cin or "").strip().upper()
    if not is_enabled() or not CIN_RE.match(cin):
        return UNAVAILABLE, None
    query = urllib.parse.urlencode({
        "api-key": os.environ["DATA_GOV_IN_API_KEY"].strip(),
        "format": "json",
        "limit": "2",
        "filters[CIN]": cin,
    })
    try:
        payload = json.loads(_open(f"{OGD_RESOURCE_URL}?{query}"))
        records = payload["records"]
        if not isinstance(records, list):
            return UNAVAILABLE, None
    except Exception as exc:  # network, timeout, JSON or schema problem; never log the URL (it holds the key)
        logger.warning("[OGD] registry lookup unavailable: %s", type(exc).__name__)
        return UNAVAILABLE, None
    if not records:
        return NOT_FOUND, None
    # If the API ignored the filter it would return unrelated rows; that is not a "not found".
    for row in records:
        if isinstance(row, dict) and str(row.get("CIN", "")).strip().upper() == cin:
            name = str(row.get("CompanyName") or "").strip()
            status = str(row.get("CompanyStatus") or "").strip()
            if not name or not status:
                return UNAVAILABLE, None
            return FOUND, OgdCompany(
                cin=cin, company_name=name, company_status=status,
                date_of_registration=(str(row.get("CompanyRegistrationdate_date") or "").strip() or None),
            )
    logger.warning("[OGD] registry lookup returned rows that do not match the requested CIN")
    return UNAVAILABLE, None
