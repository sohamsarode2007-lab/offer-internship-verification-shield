import os
import re
import csv
import datetime
import pandas as pd
import numpy as np
from rapidfuzz import fuzz

def extract_payment_requested(text, label):
    if label == 0 or not isinstance(text, str):
        return False
    text_lower = text.lower()
    triggers = [
        "deposit", "pay", "fee", "amount", "charge", "payment", "rs.", "inr",
        "transferred", "refundable", "upi", "bank account", "processing fee"
    ]
    return any(trig in text_lower for trig in triggers)

def extract_payment_amount(text):
    if not isinstance(text, str):
        return None
    # Match patterns like Rs 2500, INR 1,850, Rs. 2,000, 2000 rs, 10,000 rs
    patterns = [
        r'(?:rs\.?|inr)\s*([\d,]+)',
        r'([\d,]+)\s*(?:rs|inr|rupees)'
    ]
    for p in patterns:
        match = re.search(p, text, re.IGNORECASE)
        if match:
            val_str = match.group(1).replace(',', '')
            if val_str.isdigit() and 100 <= int(val_str) <= 500000:
                return f"INR {int(val_str)}"
    return None

def extract_payment_method(text):
    if not isinstance(text, str):
        return None
    text_lower = text.lower()
    if "upi" in text_lower or "gpay" in text_lower or "paytm" in text_lower or "phonepe" in text_lower or "@" in text_lower:
        return "UPI VPA"
    elif "bank" in text_lower or "hdfc" in text_lower or "icici" in text_lower or "account" in text_lower:
        return "Bank Transfer"
    elif "cash" in text_lower:
        return "Cash"
    return None

def extract_has_domain(text, url):
    corpus = (str(text) + " " + str(url)).lower()
    # Check for domain presence like company.com or http/https link with domain
    if re.search(r'https?://[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', corpus) or re.search(r'@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', corpus):
        # Exclude free email domains for company domain check if requested
        return True
    return False

def merge_and_deduplicate():
    print("[*] Starting Dataset Merge and Deduplication...", flush=True)
    
    # 1. Read files
    # scam_dataset.csv
    scam_csv_path = "scam_dataset.csv"
    if not os.path.exists(scam_csv_path) and os.path.exists("edi content/scam_dataset.csv"):
        scam_csv_path = "edi content/scam_dataset.csv"
    df_scam = pd.read_csv(scam_csv_path)
    
    # legit_offers_raw.csv
    legit_csv_path = os.path.join("data", "legit_offers_raw.csv")
    if not os.path.exists(legit_csv_path) and os.path.exists("edi content/data/legit_offers_raw.csv"):
        legit_csv_path = "edi content/data/legit_offers_raw.csv"
    df_legit = pd.read_csv(legit_csv_path)
    
    # reddit_scam / reddit_scams_raw.csv
    reddit_csv_path = os.path.join("data", "reddit_scams_raw.csv")
    if not os.path.exists(reddit_csv_path) and os.path.exists("edi content/data/reddit_scams_raw.csv"):
        reddit_csv_path = "edi content/data/reddit_scams_raw.csv"
    df_reddit = pd.read_csv(reddit_csv_path)
    
    # synthetic_scam.csv
    synth_csv_path = os.path.join("data", "synthetic_scam.csv")
    if not os.path.exists(synth_csv_path) and os.path.exists("edi content/data/synthetic_scam.csv"):
        synth_csv_path = "edi content/data/synthetic_scam.csv"
    df_synth = pd.read_csv(synth_csv_path)

    unified_columns = [
        "text", "label", "scam_type", "payment_requested", "payment_amount", 
        "payment_method", "urgency_language", "has_domain", "source", "url", "scraped_at"
    ]
    
    all_rows = []
    
    # Process df_scam (Consumer Complaints / Web)
    for _, row in df_scam.iterrows():
        txt = str(row.get("text", ""))
        lbl = int(row.get("label", 1))
        src = str(row.get("source", "ConsumerComplaints.in"))
        url = str(row.get("url", ""))
        scraped_at = str(row.get("scraped_at", ""))
        
        all_rows.append({
            "text": txt,
            "label": lbl,
            "scam_type": "fake_offer_complaint",
            "payment_requested": extract_payment_requested(txt, lbl),
            "payment_amount": extract_payment_amount(txt),
            "payment_method": extract_payment_method(txt),
            "urgency_language": None,
            "has_domain": extract_has_domain(txt, url),
            "source": src,
            "url": url,
            "scraped_at": scraped_at
        })
        
    # Process df_legit
    for _, row in df_legit.iterrows():
        txt = str(row.get("text", ""))
        lbl = int(row.get("label", 0))
        src = str(row.get("source", "Official Careers / Placement Cell"))
        url = str(row.get("url", ""))
        scraped_at = str(row.get("scraped_at", ""))
        
        all_rows.append({
            "text": txt,
            "label": 0,
            "scam_type": None,
            "payment_requested": False,
            "payment_amount": None,
            "payment_method": None,
            "urgency_language": None,
            "has_domain": extract_has_domain(txt, url),
            "source": src,
            "url": url,
            "scraped_at": scraped_at
        })

    # Process df_reddit
    for _, row in df_reddit.iterrows():
        txt = str(row.get("text", ""))
        lbl = int(row.get("label", 1))
        src = "Reddit"
        url = str(row.get("url", ""))
        scraped_at = str(row.get("scraped_at", ""))
        
        all_rows.append({
            "text": txt,
            "label": 1,
            "scam_type": "reddit_complaint",
            "payment_requested": extract_payment_requested(txt, lbl),
            "payment_amount": extract_payment_amount(txt),
            "payment_method": extract_payment_method(txt),
            "urgency_language": None,
            "has_domain": extract_has_domain(txt, url),
            "source": src,
            "url": url,
            "scraped_at": scraped_at
        })

    # Process df_synth
    for _, row in df_synth.iterrows():
        txt = str(row.get("text", ""))
        lbl = int(row.get("label", 1))
        scam_type = str(row.get("scam_type", "synthetic"))
        pay_req = bool(row.get("payment_requested", False))
        pay_meth = str(row.get("payment_method", "")) if pd.notna(row.get("payment_method")) and str(row.get("payment_method")).strip() else None
        urgency = str(row.get("urgency_language", "")) if pd.notna(row.get("urgency_language")) else None
        src = "synthetic"
        
        all_rows.append({
            "text": txt,
            "label": 1,
            "scam_type": scam_type,
            "payment_requested": pay_req,
            "payment_amount": extract_payment_amount(txt),
            "payment_method": pay_meth,
            "urgency_language": urgency,
            "has_domain": extract_has_domain(txt, ""),
            "source": src,
            "url": None,
            "scraped_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        })

    df_merged = pd.DataFrame(all_rows)
    print(f"\n================ BEFORE DEDUPLICATION ================")
    print(f"Total Rows: {len(df_merged)}")
    print("Class Balance (label counts):")
    print(df_merged['label'].value_counts().to_string())
    print("\nSource Distribution:")
    print(df_merged['source'].value_counts().to_string())
    print("======================================================")

    # Deduplicate near-identical rows using rapidfuzz token_sort_ratio > 90
    indices_to_keep = []
    texts = df_merged['text'].tolist()
    n = len(texts)
    visited = [False] * n

    for i in range(n):
        if visited[i]:
            continue
        visited[i] = True
        indices_to_keep.append(i)
        
        text_i = texts[i]
        for j in range(i + 1, n):
            if not visited[j]:
                # Exact or fuzzy check
                if text_i == texts[j]:
                    visited[j] = True
                elif abs(len(text_i) - len(texts[j])) < 100:
                    score = fuzz.token_sort_ratio(text_i, texts[j])
                    if score > 90:
                        visited[j] = True

    df_deduped = df_merged.iloc[indices_to_keep].reset_index(drop=True)

    print(f"\n================ AFTER DEDUPLICATION ================")
    print(f"Total Rows: {len(df_deduped)}")
    print("Class Balance (label counts):")
    print(df_deduped['label'].value_counts().to_string())
    print("\nSource Distribution:")
    print(df_deduped['source'].value_counts().to_string())
    print("=====================================================")

    # Save to /data/benchmark_dataset_v1.csv
    out_path = os.path.join("data", "benchmark_dataset_v1.csv")
    os.makedirs("data", exist_ok=True)
    df_deduped.to_csv(out_path, index=False)
    print(f"\n[+] Successfully saved benchmark dataset to {out_path}")
    
    # Sync to subfolder
    sub_out_path = os.path.join("edi content", "data", "benchmark_dataset_v1.csv")
    if os.path.exists("edi content"):
        os.makedirs(os.path.join("edi content", "data"), exist_ok=True)
        df_deduped.to_csv(sub_out_path, index=False)
        print(f"[+] Synchronized to {sub_out_path}")

if __name__ == "__main__":
    merge_and_deduplicate()
