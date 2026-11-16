"""
collect_legit_offers.py — Collects remote job-posting descriptions from public job APIs.

These sources primarily describe European/US remote vacancies, not Indian offer
letters. Do not label hand-written offer templates as authentic: such templates
are agent-written and may include invented URLs, company claims, or identifiers.
Only collected source records belong here; synthetic regression data is kept
separately and explicitly labelled.

Outputs to:
  - data/legit_offers_raw.csv

Schema:
  text, label (0), title, source, keyword, url, scraped_at
"""

import csv
import datetime
import hashlib
import logging
import re
from pathlib import Path
from typing import Dict, List, Set

import requests
from bs4 import BeautifulSoup

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("LegitOfferCollector")

CSV_FIELDNAMES = ["text", "label", "title", "source", "keyword", "url", "scraped_at"]

def clean_html(raw_html: str) -> str:
    """Clean HTML tags and normalize whitespace."""
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    text = soup.get_text(separator=" ", strip=True)
    text = text.replace("\u00a0", " ").replace("\u2014", "—").replace("\u2013", "–")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def compute_text_hash(text: str) -> str:
    """Return MD5 hash of text for deduplication."""
    norm = re.sub(r"\W+", "", text.lower())
    return hashlib.md5(norm.encode("utf-8", errors="ignore")).hexdigest()


def fetch_arbeitnow_jobs() -> List[Dict[str, str]]:
    """Fetch genuine job postings from Arbeitnow API."""
    logger.info("Fetching legitimate job postings from Arbeitnow API...")
    records = []
    url = "https://www.arbeitnow.com/api/job-board-api"

    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            jobs = r.json().get("data", [])
            logger.info(f"Retrieved {len(jobs)} raw jobs from Arbeitnow.")
            for j in jobs:
                description = clean_html(j.get("description", ""))
                # Filter for English postings and sufficient content length
                text_lower = description.lower()
                if len(description) >= 150 and any(w in text_lower for w in [" the ", " and ", " to ", " for ", " with ", " you ", " experience "]):
                    company = j.get("company_name", "Corporate Employer")
                    title = j.get("title", "Job Posting")
                    job_url = j.get("url", "https://www.arbeitnow.com")

                    records.append({
                        "text": description,
                        "label": "0",  # Legitimate label
                        "title": title,
                        "source": f"{company} (Arbeitnow Job Board)",
                        "keyword": "legitimate job posting",
                        "url": job_url,
                        "scraped_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    })
    except Exception as e:
        logger.error(f"Failed to fetch from Arbeitnow API: {e}")

    logger.info(f"Collected {len(records)} verified English job postings from Arbeitnow.")
    return records


def fetch_jobicy_jobs() -> List[Dict[str, str]]:
    """Fetch genuine job postings from Jobicy API."""
    logger.info("Fetching legitimate job postings from Jobicy API...")
    records = []
    url = "https://jobicy.com/api/v2/remote-jobs?count=50"

    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            jobs = r.json().get("jobs", [])
            logger.info(f"Retrieved {len(jobs)} raw jobs from Jobicy.")
            for j in jobs:
                description = clean_html(j.get("jobDescription", ""))
                if len(description) >= 100:
                    company = j.get("companyName", "Tech Employer")
                    title = j.get("jobTitle", "Remote Job Opportunity")
                    job_url = j.get("url", "https://jobicy.com")

                    records.append({
                        "text": description,
                        "label": "0",
                        "title": title,
                        "source": f"{company} (Jobicy Remote Portal)",
                        "keyword": "legitimate remote job",
                        "url": job_url,
                        "scraped_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    })
    except Exception as e:
        logger.error(f"Failed to fetch from Jobicy API: {e}")

    logger.info(f"Collected {len(records)} verified job postings from Jobicy.")
    return records


def fetch_remotive_jobs() -> List[Dict[str, str]]:
    """Fetch genuine job postings from Remotive API."""
    logger.info("Fetching legitimate job postings from Remotive API...")
    records = []
    url = "https://remotive.com/api/remote-jobs"

    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            jobs = r.json().get("jobs", [])
            logger.info(f"Retrieved {len(jobs)} raw jobs from Remotive.")
            for j in jobs[:50]:
                description = clean_html(j.get("description", ""))
                if len(description) >= 100:
                    company = j.get("company_name", "Tech Employer")
                    title = j.get("title", "Remote Tech Role")
                    job_url = j.get("url", "https://remotive.com")

                    records.append({
                        "text": description,
                        "label": "0",
                        "title": title,
                        "source": f"{company} (Remotive Portal)",
                        "keyword": "legitimate tech role",
                        "url": job_url,
                        "scraped_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    })
    except Exception as e:
        logger.error(f"Failed to fetch from Remotive API: {e}")

    logger.info(f"Collected {len(records)} verified job postings from Remotive.")
    return records


def build_legit_dataset(target_paths: List[Path], target_count_range=(200, 300)) -> int:
    """Collect source-backed remote job postings (not offer letters)."""
    seen_hashes: Set[str] = set()
    all_records: List[Dict[str, str]] = []

    # Add source-backed job posts only. No authored offer templates are inserted.
    jobicy_records = fetch_jobicy_jobs()
    for rec in jobicy_records:
        h = compute_text_hash(rec["text"])
        if h not in seen_hashes:
            seen_hashes.add(h)
            all_records.append(rec)

    # 3. Add Remotive jobs
    remotive_records = fetch_remotive_jobs()
    for rec in remotive_records:
        h = compute_text_hash(rec["text"])
        if h not in seen_hashes:
            seen_hashes.add(h)
            all_records.append(rec)

    # 4. Add Arbeitnow jobs to reach target range (200-300)
    arbeitnow_records = fetch_arbeitnow_jobs()
    for rec in arbeitnow_records:
        if len(all_records) >= 275:  # Target ~250-275 solid examples
            break
        h = compute_text_hash(rec["text"])
        if h not in seen_hashes:
            seen_hashes.add(h)
            all_records.append(rec)

    logger.info(f"Total legitimate records collected: {len(all_records)}")

    # Write to target paths
    for csv_path in target_paths:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with open(csv_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
            writer.writeheader()
            writer.writerows(all_records)
        logger.info(f"Successfully saved {len(all_records)} records to {csv_path}")

    return len(all_records)


if __name__ == "__main__":
    out_paths = [
        Path("c:/Users/hp/Downloads/edi content/data/legit_offers_raw.csv"),
        Path("c:/Users/hp/Downloads/edi content/edi content/data/legit_offers_raw.csv"),
    ]
    build_legit_dataset(out_paths)
