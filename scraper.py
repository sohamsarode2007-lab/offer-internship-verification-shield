"""
scraper.py — Scrapes scam complaint descriptions from consumer grievance portals.

Supported Platforms:
  - ConsumerComplaints.in (direct search endpoint & complaint pages)
  - Voxya.com (complaint records & search gateway)

Key Features:
  - Parses search results for keywords like 'internship security deposit' and 'fake offer letter'
  - Extracts clean, high-quality complaint narrative text
  - Labels all records as scams (label=1)
  - Appends directly into 'scam_dataset.csv' with real-time flushing
  - Prevents duplicate entries via normalized MD5 content hashing
  - Implements domain-relevance verification to filter out non-scam noise
  - Proper browser User-Agent rotation and standard headers to prevent blocking
  - Resilient network session with HTTPAdapter, retries, exponential backoff, and polite throttling
"""

import argparse
import csv
import datetime
import hashlib
import logging
import os
import random
import re
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Dict, List, Optional, Set

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

# ---------------------------------------------------------------------------
# Configuration & Constants
# ---------------------------------------------------------------------------

DEFAULT_KEYWORDS = [
    "internship security deposit",
    "fake offer letter",
    "internship scam",
    "fake job offer",
    "job offer registration fee",
]

CSV_FIELDNAMES = [
    "text",
    "label",
    "title",
    "source",
    "keyword",
    "url",
    "scraped_at",
]

USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
    ),
]

# Relevance filter keywords to discard unrelated complaints (e.g. consumer product issues)
RELEVANCE_KEYWORDS = [
    "offer",
    "intern",
    "job",
    "deposit",
    "interview",
    "stipend",
    "recruitment",
    "hr",
    "salary",
    "fee",
    "charge",
    "cheat",
    "scam",
    "fraud",
    "fake",
    "selection",
    "joining",
    "appointment",
    "registration",
    "training",
    "candidate",
    "consultancy",
    "placement",
]

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ScamScraper")


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def create_resilient_session(retries: int = 3, backoff_factor: float = 1.0) -> requests.Session:
    """Create a requests.Session configured with connection retries and realistic headers."""
    session = requests.Session()
    retry_strategy = Retry(
        total=retries,
        backoff_factor=backoff_factor,
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    session.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    })
    return session


def clean_text(raw_text: str) -> str:
    """Normalize extracted complaint text by removing UI noise, vote counters, and excess whitespace."""
    if not raw_text:
        return ""
    # Remove UI artifacts like 'Was this information helpful? ...'
    text = re.sub(r"Was this information helpful\?.*$", "", raw_text, flags=re.IGNORECASE)
    # Remove vote counts or button artifacts
    text = re.sub(r"No \(\d+\)\s*Yes \(\d+\)", "", text)
    # Remove '(complaint)' badge tag
    text = re.sub(r"\(complaint\)", "", text, flags=re.IGNORECASE)
    # Normalize unicode spaces and dashes
    text = text.replace("\u00a0", " ").replace("\u2014", "—").replace("\u2013", "–")
    # Normalize multiple whitespaces/newlines to single space
    text = re.sub(r"\s+", " ", text).strip()
    return text


def compute_text_hash(text: str) -> str:
    """Return MD5 hash of normalized text for fast deduplication."""
    norm = re.sub(r"\W+", "", text.lower())
    return hashlib.md5(norm.encode("utf-8", errors="ignore")).hexdigest()


def is_relevant_scam(text: str, title: str) -> bool:
    """Verify complaint description or title contains job/internship/offer scam indicators."""
    combined = f"{text} {title}".lower()
    return any(k in combined for k in RELEVANCE_KEYWORDS)


def load_existing_hashes(csv_path: Path) -> Set[str]:
    """Read existing complaint hashes from CSV file if it exists, to avoid duplicates across runs."""
    seen_hashes: Set[str] = set()
    if not csv_path.exists():
        return seen_hashes

    try:
        with open(csv_path, mode="r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                text = row.get("text", "")
                if text:
                    seen_hashes.add(compute_text_hash(text))
        logger.info(f"Loaded {len(seen_hashes)} existing records from {csv_path.name}")
    except Exception as e:
        logger.warning(f"Could not load existing CSV records ({e}); starting fresh deduplication.")
    return seen_hashes


def append_to_csv(csv_path: Path, record: Dict[str, str]) -> bool:
    """
    Append a single complaint row directly into the CSV file.
    Creates the file and writes headers if it does not already exist.
    """
    file_exists = csv_path.exists() and csv_path.stat().st_size > 0
    try:
        with open(csv_path, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
            if not file_exists:
                writer.writeheader()
            writer.writerow(record)
            f.flush()
        return True
    except Exception as e:
        logger.error(f"Failed to append row to {csv_path}: {e}")
        return False


# ---------------------------------------------------------------------------
# Scraper Modules
# ---------------------------------------------------------------------------

def scrape_consumer_complaints(
    session: requests.Session,
    keyword: str,
    max_pages: int,
    seen_hashes: Set[str],
    csv_path: Path,
    delay: float = 1.5,
) -> int:
    """
    Scrapes scam complaints from ConsumerComplaints.in search results.
    Visits standalone complaint pages for full reviewBody text, or extracts
    the card snippet for company page results.
    """
    base_url = "https://www.consumercomplaints.in"
    saved_count = 0
    logger.info(f"[ConsumerComplaints.in] Searching for: '{keyword}' (up to {max_pages} pages)...")

    for page in range(1, max_pages + 1):
        search_url = f"{base_url}/?search={urllib.parse.quote_plus(keyword)}&page={page}"
        logger.info(f"[ConsumerComplaints.in] Fetching page {page}: {search_url}")

        try:
            session.headers["User-Agent"] = random.choice(USER_AGENTS)
            resp = session.get(search_url, timeout=15)
            if resp.status_code != 200:
                logger.warning(
                    f"[ConsumerComplaints.in] HTTP {resp.status_code} on page {page}. Skipping."
                )
                break
        except requests.RequestException as e:
            logger.error(f"[ConsumerComplaints.in] Request error fetching search results: {e}")
            break

        soup = BeautifulSoup(resp.text, "html.parser")
        boxes = soup.select(".complaint-box-results")
        if not boxes:
            logger.info(f"[ConsumerComplaints.in] No complaint boxes found on page {page}. Done.")
            break

        logger.info(f"[ConsumerComplaints.in] Found {len(boxes)} items on page {page}.")

        for box in boxes:
            title_el = box.select_one("a.complaint-box-results__title")
            title = clean_text(title_el.get_text(strip=True)) if title_el else ""
            href = title_el["href"] if title_el and "href" in title_el.attrs else ""

            complaint_url = ""
            if href:
                complaint_url = base_url + href if href.startswith("/") else href

            full_text = ""

            # Check if this is a dedicated, standalone complaint page
            is_standalone = bool(
                re.search(r"-c\d+(\.html)?$", complaint_url)
                or "/complaints/" in complaint_url
            ) and ("/page/" not in complaint_url and "/bycompany/" not in complaint_url)

            if is_standalone and complaint_url:
                try:
                    time.sleep(delay + random.uniform(0.1, 0.4))
                    session.headers["User-Agent"] = random.choice(USER_AGENTS)
                    detail_resp = session.get(complaint_url, timeout=12)
                    if detail_resp.status_code == 200:
                        detail_soup = BeautifulSoup(detail_resp.text, "html.parser")
                        body_el = detail_soup.find(attrs={"itemprop": "reviewBody"})
                        if not body_el:
                            body_el = detail_soup.select_one(
                                ".complaint-description, .complaint_text, td.complaint"
                            )
                        if body_el:
                            full_text = clean_text(body_el.get_text(separator=" ", strip=True))
                except requests.RequestException as err:
                    logger.debug(f"Could not load detail page {complaint_url}: {err}")

            # For company listing pages or fallback, extract the exact snippet from the search card
            if not full_text:
                text_el = box.find("div", class_="complaint-box-results__text")
                if text_el:
                    full_text = clean_text(text_el.get_text(separator=" ", strip=True))

            # Validate text length
            if len(full_text) < 40:
                continue

            # Verify relevance to scam / job / internship domains
            if not is_relevant_scam(full_text, title):
                logger.debug(f"Skipping non-scam / irrelevant item: {title[:40]}...")
                continue

            # Deduplication
            text_hash = compute_text_hash(full_text)
            if text_hash in seen_hashes:
                logger.debug(f"Skipping duplicate complaint: {title[:40]}...")
                continue

            record = {
                "text": full_text,
                "label": "1",  # Scam label
                "title": title,
                "source": "ConsumerComplaints.in",
                "keyword": keyword,
                "url": complaint_url,
                "scraped_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }

            if append_to_csv(csv_path, record):
                seen_hashes.add(text_hash)
                saved_count += 1
                logger.info(
                    f"[ConsumerComplaints.in] Saved scam #{saved_count} [{len(full_text)} chars]: "
                    f"\"{title[:60]}...\""
                )

        time.sleep(delay + random.uniform(0.2, 0.5))

    return saved_count


def scrape_voxya(
    session: requests.Session,
    keyword: str,
    seen_hashes: Set[str],
    csv_path: Path,
    delay: float = 1.5,
) -> int:
    """
    Scrapes scam complaints from Voxya.com.
    Queries Voxya complaint threads matching target keywords via DuckDuckGo gateway,
    then parses each Voxya complaint page to extract the full complaint description.
    """
    logger.info(f"[Voxya] Searching for: '{keyword}'...")
    saved_count = 0

    search_query = f"site:voxya.com/consumer-complaints {keyword}"
    ddg_url = "https://html.duckduckgo.com/html/"

    voxya_urls: List[str] = []
    try:
        session.headers["User-Agent"] = random.choice(USER_AGENTS)
        resp = session.post(
            ddg_url,
            data={"q": search_query},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.select("a.result__url, a.result__snippet"):
                href = a.get("href", "")
                if "voxya.com/consumer-complaints/" in href:
                    match = re.search(r"uddg=([^&]+)", href)
                    clean_url = urllib.parse.unquote(match.group(1)) if match else href
                    if clean_url not in voxya_urls:
                        voxya_urls.append(clean_url)
    except requests.RequestException as e:
        logger.warning(f"[Voxya] Search query request failed: {e}")

    logger.info(f"[Voxya] Discovered {len(voxya_urls)} complaint URLs matching '{keyword}'.")

    for url in voxya_urls:
        try:
            time.sleep(delay + random.uniform(0.2, 0.5))
            session.headers["User-Agent"] = random.choice(USER_AGENTS)
            c_resp = session.get(url, timeout=12)
            if c_resp.status_code != 200:
                continue

            c_soup = BeautifulSoup(c_resp.text, "html.parser")
            title = c_soup.title.string.strip() if c_soup.title and c_soup.title.string else ""
            title = clean_text(title)

            # In Voxya, complaint narrative paragraphs are styled with text-custom-22 or text-grey
            complaint_text = ""
            for p in c_soup.find_all("p"):
                classes = " ".join(p.get("class", []))
                text = p.get_text(strip=True)
                if (
                    "text-custom-22" in classes
                    or ("text-grey" in classes and len(text) > 40)
                ):
                    if not any(noise in text.lower() for noise in ["voxya", "rights reserved", "legal advice", "file online consumer"]):
                        complaint_text = clean_text(text)
                        break

            # Fallback scan across all paragraphs
            if not complaint_text:
                for p in c_soup.find_all("p"):
                    text = p.get_text(strip=True)
                    if (
                        len(text) > 60
                        and not any(n in text.lower() for n in ["voxya", "rights reserved", "legal advice", "consumer court and forum"])
                    ):
                        complaint_text = clean_text(text)
                        break

            if len(complaint_text) < 40:
                continue

            # Verify relevance
            if not is_relevant_scam(complaint_text, title):
                continue

            text_hash = compute_text_hash(complaint_text)
            if text_hash in seen_hashes:
                continue

            record = {
                "text": complaint_text,
                "label": "1",  # Scam label
                "title": title,
                "source": "Voxya",
                "keyword": keyword,
                "url": url,
                "scraped_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }

            if append_to_csv(csv_path, record):
                seen_hashes.add(text_hash)
                saved_count += 1
                logger.info(
                    f"[Voxya] Saved scam #{saved_count} [{len(complaint_text)} chars]: "
                    f"\"{title[:60]}...\""
                )

        except requests.RequestException as err:
            logger.debug(f"[Voxya] Error loading complaint {url}: {err}")
            continue

    return saved_count


# ---------------------------------------------------------------------------
# Main Runner
# ---------------------------------------------------------------------------

def run_scraper(
    keywords: List[str],
    output_file: str,
    max_pages: int = 3,
    delay: float = 1.5,
    sources: str = "all",
) -> None:
    """Execute the full scraping workflow across specified keywords and sites."""
    csv_path = Path(output_file).resolve()
    logger.info("=" * 60)
    logger.info("Starting Scam Complaint Scraper")
    logger.info(f"Target Output: {csv_path}")
    logger.info(f"Keywords: {keywords}")
    logger.info(f"Max Pages / Keyword: {max_pages}")
    logger.info(f"Inter-request Delay: {delay}s")
    logger.info(f"Sources: {sources}")
    logger.info("=" * 60)

    seen_hashes = load_existing_hashes(csv_path)
    session = create_resilient_session()

    total_new_records = 0

    for kw in keywords:
        kw_saved = 0
        logger.info(f"\n>>> Processing Keyword: '{kw}' <<<")

        # 1. Scrape ConsumerComplaints.in
        if sources in ("all", "consumercomplaints"):
            cc_count = scrape_consumer_complaints(
                session=session,
                keyword=kw,
                max_pages=max_pages,
                seen_hashes=seen_hashes,
                csv_path=csv_path,
                delay=delay,
            )
            kw_saved += cc_count

        # 2. Scrape Voxya
        if sources in ("all", "voxya"):
            voxya_count = scrape_voxya(
                session=session,
                keyword=kw,
                seen_hashes=seen_hashes,
                csv_path=csv_path,
                delay=delay,
            )
            kw_saved += voxya_count

        total_new_records += kw_saved
        logger.info(f"Keyword '{kw}' complete: {kw_saved} new scam complaints collected.")

    logger.info("\n" + "=" * 60)
    logger.info(f"SCRAPING RUN COMPLETE: {total_new_records} new scam complaints saved.")
    logger.info(f"Total records now in {csv_path.name}: {len(seen_hashes)}")
    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Scrape scam complaint descriptions from consumer grievance platforms."
    )
    parser.add_argument(
        "--keywords",
        nargs="+",
        default=DEFAULT_KEYWORDS,
        help="List of search keywords (e.g. 'internship security deposit' 'fake offer letter').",
    )
    parser.add_argument(
        "--output",
        default="scam_dataset.csv",
        help="Path to the destination CSV file (default: scam_dataset.csv).",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=3,
        help="Maximum search result pages to scrape per keyword for paginated sites (default: 3).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.5,
        help="Polite delay between HTTP requests in seconds (default: 1.5).",
    )
    parser.add_argument(
        "--sources",
        choices=["all", "consumercomplaints", "voxya"],
        default="all",
        help="Which platforms to scrape from (default: all).",
    )

    args = parser.parse_args()
    run_scraper(
        keywords=args.keywords,
        output_file=args.output,
        max_pages=args.max_pages,
        delay=args.delay,
        sources=args.sources,
    )


if __name__ == "__main__":
    main()
