"""Download the data.gov.in "RoC-wise Company Master Data" into the local company-master SQLite.

Needs a personal API key in DATA_GOV_IN_API_KEY (data.gov.in > My Account). Pages through the
resource politely (at least 0.5 s between requests), keeps only CIN, name, status and
registration date, and loads each page with scripts.load_mca_master.load_csv, so the same
rules apply (rows are inserted or updated; synthetic and real data are never mixed).

It is resumable: if a page keeps failing the script stops and prints the offset to pass to
--start-offset. The API key is never printed or logged. Data is a periodic snapshot published
under the Government Open Data License - India; it is not a live registry.

  $env:DATA_GOV_IN_API_KEY = "..."
  .\\.venv\\Scripts\\python.exe -m scripts.sync_ogd_master --max-pages 5      # small trial first
"""
import argparse
import csv
import json
import os
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

from app.services.ogd_registry import CIN_RE, OGD_RESOURCE_URL
from scripts.load_mca_master import load_csv

FIELDS = ["CIN", "CompanyName", "CompanyStatus", "CompanyRegistrationdate_date"]
MIN_DELAY = 0.5
MAX_PAGE_SIZE = 1000
RETRIES = 3
MAX_PAGE_BYTES = 8 * 1024 * 1024


def _open(url: str, timeout: float) -> bytes:
    """Fetch one page (size-capped). Replaceable in tests."""
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (fixed https host)
        return response.read(MAX_PAGE_BYTES)


def _fetch_page(key: str, offset: int, limit: int, timeout: float, sleep=time.sleep):
    query = urllib.parse.urlencode({"api-key": key, "format": "json", "offset": offset, "limit": limit})
    last = "unknown"
    for attempt in range(RETRIES):
        try:
            payload = json.loads(_open(f"{OGD_RESOURCE_URL}?{query}", timeout))
            records = payload["records"]
            if isinstance(records, list):
                return records, payload.get("total")
            last = "unexpected payload"
        except Exception as exc:  # never include the message: it can contain the URL with the key
            last = type(exc).__name__
        sleep(2 ** attempt)
    raise RuntimeError(f"page at offset {offset} failed after {RETRIES} tries ({last})")


def _clean(records):
    """Keep only valid CIN rows and only the four fields we use."""
    rows = []
    for row in records:
        if not isinstance(row, dict):
            continue
        cin = str(row.get("CIN") or "").strip().upper()
        if CIN_RE.match(cin):
            rows.append({"CIN": cin, **{k: str(row.get(k) or "").strip() for k in FIELDS[1:]}})
    return rows


def sync(db: Path, page_size: int = 500, max_pages=None, start_offset: int = 0, delay: float = MIN_DELAY,
         timeout: float = 30.0, sleep=time.sleep, out=print) -> int:
    key = os.getenv("DATA_GOV_IN_API_KEY", "").strip()
    if not key:
        out("DATA_GOV_IN_API_KEY is not set.")
        return 2
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    delay = max(delay, MIN_DELAY)
    offset, pages, loaded = start_offset, 0, 0
    while max_pages is None or pages < max_pages:
        try:
            records, total = _fetch_page(key, offset, page_size, timeout, sleep)
        except RuntimeError as exc:
            out(f"Stopped: {exc}. Loaded {loaded} rows this run. Resume with --start-offset {offset}.")
            return 1
        if not records:
            break
        rows = _clean(records)
        if rows:
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "page.csv"
                with path.open("w", newline="", encoding="utf-8") as stream:
                    writer = csv.DictWriter(stream, fieldnames=FIELDS)
                    writer.writeheader()
                    writer.writerows(rows)
                loaded += load_csv(path, db)
        offset += len(records)
        pages += 1
        out(f"offset {offset}: {loaded} rows loaded so far")
        if isinstance(total, (int, str)) and str(total).isdigit() and offset >= int(total):
            break
        sleep(delay)
    out(f"Done. Loaded or updated {loaded} rows in {db}. Next offset: {offset}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=Path("data/mca_master.sqlite3"))
    parser.add_argument("--page-size", type=int, default=500)
    parser.add_argument("--max-pages", type=int, default=None, help="stop after this many pages (use a small number first)")
    parser.add_argument("--start-offset", type=int, default=0)
    parser.add_argument("--delay", type=float, default=MIN_DELAY, help="seconds between requests (minimum 0.5)")
    args = parser.parse_args()
    return sync(args.db, args.page_size, args.max_pages, args.start_offset, args.delay)


if __name__ == "__main__":
    sys.exit(main())
