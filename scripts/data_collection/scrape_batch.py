"""
scrape_batch.py — Scrapes ConsumerComplaints.in for specific scam keyword sets
and appends new records to scam_dataset.csv with URL deduplication.

Target Keywords:
  - training fee fraud
  - refundable security deposit job
  - fake HR call
  - joining bonus advance payment
  - fake appointment letter
  - backdoor job offer

Schema:
  text, label (1), title, source, keyword, url, scraped_at
"""

import csv
import datetime
import logging
import random
import re
import time
import urllib.parse
from pathlib import Path
from typing import Dict, List, Set

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("BatchScraper")

CSV_FIELDNAMES = ["text", "label", "title", "source", "keyword", "url", "scraped_at"]

TARGET_KEYWORDS = [
    "training fee fraud",
    "refundable security deposit job",
    "fake HR call",
    "joining bonus advance payment",
    "fake appointment letter",
    "backdoor job offer",
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

RELEVANCE_KEYWORDS = [
    "offer", "intern", "job", "deposit", "interview", "stipend",
    "recruitment", "hr", "salary", "fee", "charge", "cheat",
    "scam", "fraud", "fake", "selection", "joining", "appointment",
    "registration", "training", "candidate", "consultancy", "placement", "bonus"
]


def create_session() -> requests.Session:
    """Create session with retry strategy and realistic browser headers."""
    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
    })
    return session


def clean_text(raw_text: str) -> str:
    """Clean UI noise and normalize text."""
    if not raw_text:
        return ""
    text = re.sub(r"Was this information helpful\?.*$", "", raw_text, flags=re.IGNORECASE)
    text = re.sub(r"No \(\d+\)\s*Yes \(\d+\)", "", text)
    text = re.sub(r"\(complaint\)", "", text, flags=re.IGNORECASE)
    text = text.replace("\u00a0", " ").replace("\u2014", "—").replace("\u2013", "–")
    return re.sub(r"\s+", " ", text).strip()


def load_existing_urls(csv_path: Path) -> Set[str]:
    """Load existing URLs from CSV to enable URL-based deduplication."""
    seen_urls: Set[str] = set()
    if not csv_path.exists():
        return seen_urls

    try:
        with open(csv_path, mode="r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                url = row.get("url", "").strip()
                if url:
                    seen_urls.add(url)
        logger.info(f"Loaded {len(seen_urls)} existing URLs from {csv_path.name}")
    except Exception as e:
        logger.warning(f"Could not load existing CSV URLs ({e}).")
    return seen_urls


def is_relevant(text: str, title: str) -> bool:
    """Verify complaint is relevant to employment / job / offer scam."""
    combined = f"{text} {title}".lower()
    return any(k in combined for k in RELEVANCE_KEYWORDS)


def append_record(csv_path: Path, record: Dict[str, str]) -> bool:
    """Append a single record row directly to CSV."""
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
        logger.error(f"Error appending row to {csv_path}: {e}")
        return False


def run_batch_scrape(csv_paths: List[Path], max_pages_per_kw: int = 2, delay: float = 1.5) -> int:
    """Execute scraping across specified keyword sets and append to CSV."""
    main_csv = csv_paths[0]
    seen_urls = load_existing_urls(main_csv)
    session = create_session()

    base_url = "https://www.consumercomplaints.in"
    total_added = 0

    logger.info("=" * 60)
    logger.info(f"Starting ConsumerComplaints.in Batch Scraper for {len(TARGET_KEYWORDS)} Keyword Sets")
    logger.info(f"Keywords: {TARGET_KEYWORDS}")
    logger.info(f"Target CSV: {main_csv}")
    logger.info("=" * 60)

    for kw in TARGET_KEYWORDS:
        kw_added = 0
        logger.info(f"\n>>> Processing Keyword Set: '{kw}' <<<")

        for page in range(1, max_pages_per_kw + 1):
            search_url = f"{base_url}/?search={urllib.parse.quote_plus(kw)}&page={page}"
            logger.info(f"[ConsumerComplaints.in] Fetching page {page}: {search_url}")

            try:
                session.headers["User-Agent"] = random.choice(USER_AGENTS)
                resp = session.get(search_url, timeout=15)
                if resp.status_code != 200:
                    logger.warning(f"HTTP {resp.status_code} on page {page}. Skipping.")
                    break
            except requests.RequestException as e:
                logger.error(f"Request error: {e}")
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            boxes = soup.select(".complaint-box-results")
            if not boxes:
                logger.info(f"No more results found for '{kw}' on page {page}.")
                break

            logger.info(f"Found {len(boxes)} items on page {page}.")

            for box in boxes:
                title_el = box.select_one("a.complaint-box-results__title")
                title = clean_text(title_el.get_text(strip=True)) if title_el else ""
                href = title_el["href"] if title_el and "href" in title_el.attrs else ""

                if not href:
                    continue

                full_url = base_url + href if href.startswith("/") else href

                # DEDUPLICATION BY URL COLUMN
                if full_url in seen_urls:
                    logger.debug(f"Skipping already scraped URL: {full_url}")
                    continue

                full_text = ""
                is_standalone = bool(
                    re.search(r"-c\d+(\.html)?$", full_url)
                    or "/complaints/" in full_url
                ) and ("/page/" not in full_url and "/bycompany/" not in full_url)

                if is_standalone:
                    try:
                        time.sleep(delay + random.uniform(0.1, 0.4))
                        session.headers["User-Agent"] = random.choice(USER_AGENTS)
                        detail_resp = session.get(full_url, timeout=12)
                        if detail_resp.status_code == 200:
                            detail_soup = BeautifulSoup(detail_resp.text, "html.parser")
                            body_el = detail_soup.find(attrs={"itemprop": "reviewBody"})
                            if not body_el:
                                body_el = detail_soup.select_one(".complaint-description, .complaint_text, td.complaint")
                            if body_el:
                                full_text = clean_text(body_el.get_text(separator=" ", strip=True))
                    except requests.RequestException as err:
                        logger.debug(f"Could not load detail page {full_url}: {err}")

                # Fallback to search result card text snippet
                if not full_text:
                    text_el = box.find("div", class_="complaint-box-results__text")
                    if text_el:
                        full_text = clean_text(text_el.get_text(separator=" ", strip=True))

                if len(full_text) < 30:
                    continue

                if not is_relevant(full_text, title):
                    logger.debug(f"Skipping irrelevant complaint: {title[:40]}")
                    continue

                record = {
                    "text": full_text,
                    "label": "1",
                    "title": title,
                    "source": "ConsumerComplaints.in",
                    "keyword": kw,
                    "url": full_url,
                    "scraped_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                }

                # Append to all target CSV locations
                success = True
                for p in csv_paths:
                    if not append_record(p, record):
                        success = False

                if success:
                    seen_urls.add(full_url)
                    kw_added += 1
                    total_added += 1
                    logger.info(f"Saved scam complaint #{total_added} [{len(full_text)} chars]: \"{title[:60]}...\"")

            time.sleep(delay + random.uniform(0.2, 0.5))

        logger.info(f"Keyword '{kw}' completed: {kw_added} new records added.")

    logger.info("=" * 60)
    logger.info(f"BATCH SCRAPING COMPLETE: Added {total_added} new unique scam complaints.")
    logger.info(f"Total unique URLs in CSV: {len(seen_urls)}")
    logger.info("=" * 60)
    return total_added


if __name__ == "__main__":
    targets = [
        Path("c:/Users/hp/Downloads/edi content/edi content/scam_dataset.csv"),
        Path("c:/Users/hp/Downloads/edi content/scam_dataset.csv"),
    ]
    run_batch_scrape(targets, max_pages_per_kw=2)
