import httpx
import bs4
import datetime
import csv
import os
import re
import time
import random
import urllib.parse
from bs4 import XMLParsedAsHTMLWarning
import warnings

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

SUBREDDITS = ["developersIndia", "Btechtards"]
KEYWORDS = ["fake offer", "scam internship", "fake HR", "don't pay them", "dont pay them"]

CUTOFF_DATE = datetime.datetime(2023, 1, 1, tzinfo=datetime.timezone.utc)

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
]

def parse_iso_date(date_str):
    if not date_str:
        return None
    try:
        date_str = date_str.replace('Z', '+00:00')
        return datetime.datetime.fromisoformat(date_str)
    except Exception:
        return None

def clean_text(text):
    if not text:
        return ""
    soup = bs4.BeautifulSoup(text, 'html.parser')
    clean = soup.get_text(separator=' ')
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean

def determine_confidence(title, post_text):
    combined_op = (title + " " + post_text).lower()
    
    explicit_op_triggers = [
        "scammed me", "they scammed", "lost money", "paid them", "it was fake",
        "it is fake", "confirmed scam", "fake offer letter", "fake hr", "fraud company",
        "scam company", "got scammed", "fake company", "definitely a scam",
        "100% scam", "dont pay", "don't pay", "they asked money", "asking money",
        "security deposit", "cheated me", "fake appointment", "backdoor scam", "cheated"
    ]
    
    for trigger in explicit_op_triggers:
        if trigger in combined_op:
            return "HIGH"
            
    return "MEDIUM"

def fetch_url_with_retry(url, max_retries=4):
    for attempt in range(max_retries):
        headers = {'User-Agent': random.choice(USER_AGENTS)}
        try:
            with httpx.Client(headers=headers, timeout=25.0, follow_redirects=True) as client:
                resp = client.get(url)
                if resp.status_code == 200:
                    return resp
                elif resp.status_code == 429:
                    wait_time = (attempt + 1) * 8
                    print(f"        [!] Rate limited (429). Waiting {wait_time}s before retry...", flush=True)
                    time.sleep(wait_time)
                else:
                    print(f"        [-] HTTP Status {resp.status_code} for {url}", flush=True)
                    return None
        except Exception as e:
            print(f"        [-] Request exception: {e}", flush=True)
            time.sleep(3)
    return None

def fetch_reddit_scams():
    results = []
    seen_urls = set()

    for sub in SUBREDDITS:
        for kw in KEYWORDS:
            print(f"[*] Fetching r/{sub} for keyword: '{kw}'...", flush=True)
            encoded_kw = urllib.parse.quote(kw)
            search_url = f"https://www.reddit.com/r/{sub}/search.rss?q={encoded_kw}&restrict_sr=on&sort=new&limit=100"
            
            time.sleep(4.0)
            resp = fetch_url_with_retry(search_url)
            if not resp or resp.status_code != 200:
                print(f"    [-] Failed to retrieve search feed for '{kw}' in r/{sub}", flush=True)
                continue
            
            soup = bs4.BeautifulSoup(resp.text, 'html.parser')
            entries = soup.find_all('entry')
            print(f"    [+] Found {len(entries)} RSS entries for '{kw}' in r/{sub}", flush=True)
            
            kw_added = 0
            for entry in entries:
                try:
                    title_elem = entry.find('title')
                    link_elem = entry.find('link')
                    updated_elem = entry.find('updated') or entry.find('published')
                    content_elem = entry.find('content')
                    
                    title = clean_text(title_elem.text) if title_elem else ""
                    link = link_elem['href'] if link_elem and 'href' in link_elem.attrs else ""
                    updated_str = updated_elem.text if updated_elem else ""
                    post_text = clean_text(content_elem.text) if content_elem else ""
                    
                    if not link:
                        continue
                        
                    clean_url = link.split('?')[0]
                    if clean_url in seen_urls:
                        continue
                        
                    pub_date = parse_iso_date(updated_str)
                    if pub_date and pub_date < CUTOFF_DATE:
                        continue
                        
                    confidence = determine_confidence(title, post_text)
                    scraped_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    
                    seen_urls.add(clean_url)
                    
                    text_to_save = f"{title}. {post_text}".strip()
                    if len(text_to_save) < 15:
                        text_to_save = title
                        
                    row = {
                        "text": text_to_save,
                        "label": 1,
                        "title": title,
                        "source": "Reddit",
                        "keyword": kw,
                        "url": clean_url,
                        "scraped_at": scraped_at,
                        "confidence": confidence
                    }
                    
                    results.append(row)
                    kw_added += 1
                    
                except Exception as e:
                    print(f"        [-] Error parsing entry: {e}", flush=True)

            print(f"    [+] Added {kw_added} new items for '{kw}' in r/{sub}", flush=True)

    print(f"\n[+] Total unique Reddit records retrieved: {len(results)}", flush=True)
    return results

def append_to_scam_dataset(new_records, dataset_path):
    if not os.path.exists(dataset_path):
        print(f"[-] Dataset path {dataset_path} does not exist!")
        return 0

    existing_urls = set()
    existing_headers = []
    
    with open(dataset_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        try:
            existing_headers = next(reader)
        except StopIteration:
            existing_headers = ["text", "label", "title", "source", "keyword", "url", "scraped_at"]
            
        url_idx = existing_headers.index("url") if "url" in existing_headers else 5
        
        for row in reader:
            if len(row) > url_idx:
                existing_urls.add(row[url_idx].strip())

    has_confidence = "confidence" in existing_headers
    if not has_confidence:
        existing_headers.append("confidence")

    added_count = 0
    rows_to_keep = []
    with open(dataset_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        for row in reader:
            if not has_confidence:
                row.append("HIGH")
            rows_to_keep.append(row)

    for rec in new_records:
        if rec["url"] not in existing_urls:
            existing_urls.add(rec["url"])
            new_row = [
                rec["text"],
                rec["label"],
                rec["title"],
                rec["source"],
                rec["keyword"],
                rec["url"],
                rec["scraped_at"],
                rec["confidence"]
            ]
            rows_to_keep.append(new_row)
            added_count += 1

    with open(dataset_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(existing_headers)
        writer.writerows(rows_to_keep)

    print(f"[+] Appended {added_count} new Reddit records to {dataset_path}. Total rows now: {len(rows_to_keep)}", flush=True)
    return added_count

if __name__ == "__main__":
    records = fetch_reddit_scams()
    
    data_dir = "data"
    os.makedirs(data_dir, exist_ok=True)
    raw_csv = os.path.join(data_dir, "reddit_scams_raw.csv")
    
    fieldnames = ["text", "label", "title", "source", "keyword", "url", "scraped_at", "confidence"]
    with open(raw_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)
    print(f"[+] Saved raw dataset to {raw_csv}", flush=True)
    
    root_dataset = os.path.abspath(os.path.join(os.path.dirname(__file__), "scam_dataset.csv"))
    sub_dataset = os.path.abspath(os.path.join(os.path.dirname(__file__), "edi content", "scam_dataset.csv"))
    
    if os.path.exists(root_dataset):
        append_to_scam_dataset(records, root_dataset)
    if os.path.exists(sub_dataset) and sub_dataset != root_dataset:
        append_to_scam_dataset(records, sub_dataset)
