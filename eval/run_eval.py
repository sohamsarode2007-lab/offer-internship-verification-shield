"""Run the synthetic regression cases through local rules or a live API."""

import argparse
import csv
import os
import re
import sys
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = Path(__file__).with_name("edge_cases.csv")
BANDS = ["likely legitimate", "insufficient evidence, verify manually", "high risk"]


def load_cases():
    with CASES_PATH.open(encoding="utf-8", newline="") as source:
        cases = list(csv.DictReader(source))
    if not cases:
        raise ValueError("edge_cases.csv contains no rows")
    for case in cases:
        if case.get("synthetic", "").lower() != "true":
            raise ValueError(f"{case.get('case_id')}: all evaluation rows must be labelled synthetic=true")
        if case.get("truth") not in {"scam", "legitimate"}:
            raise ValueError(f"{case.get('case_id')}: unsupported truth label")
        if case.get("input_type", "text") not in {"text", "eml"}:
            raise ValueError(f"{case.get('case_id')}: unsupported input_type")
        if case.get("expected_band") not in BANDS:
            raise ValueError(f"{case.get('case_id')}: unsupported expected band")
        if not case.get("expected_basis"):
            raise ValueError(f"{case.get('case_id')}: expected_basis must record the hand calculation")
    return cases


def local_band(case):
    # Synthetic .example domains are configured as demo fixtures to keep this path
    # offline and deterministic. No external DNS or registry calls are made.
    from app.services import domain_verification, fact_extraction, gstin_verification
    from app.services import payment_detection, risk_scoring

    from app.services import email_auth, ingestion
    if case.get("input_type", "text") == "eml":
        parsed = email_auth.parse_eml((ROOT / case["text"]).read_bytes())
        body, _ = ingestion.ingest_offer(text=parsed["body_text"])
        pieces = [body] if body else []
        for attachment in parsed["attachments"]:
            extracted, _ = ingestion.ingest_offer(file_bytes=attachment["data"], filename=attachment["filename"])
            if extracted:
                pieces.append(extracted)
        text = "\n".join(pieces)
        facts = fact_extraction.extract_facts(text)
        body_domain = facts.get("sender_domain", {}).get("value")
        auth_facts = dict(facts)
        auth_facts["sender_domain"] = {"value": parsed.get("sender_domain")}
        domain_check = domain_verification.verify_domain(auth_facts)
        if body_domain:
            domain_check["details"] += f" Body-claimed domain: '{body_domain}'."
        auth_check = email_auth.verify_sender_authentication(parsed, facts)
    else:
        text = case["text"]
        facts = fact_extraction.extract_facts(text)
        domain_check = domain_verification.verify_domain(facts)
        auth_check = email_auth.not_applicable()
    checks = [domain_check, gstin_verification.verify_gstin(facts),
              payment_detection.detect_payment_demand(facts), auth_check]
    return risk_scoring.calculate_risk_score(checks, facts=facts)["risk_band"]


def live_band(case, base_url):
    boundary = "----CodexEvalBoundary"
    if case.get("input_type", "text") == "eml":
        filename = Path(case["text"]).name
        data = (ROOT / case["text"]).read_bytes()
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
                "Content-Type: message/rfc822\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
        content_type = f"multipart/form-data; boundary={boundary}"
        request = urllib.request.Request(f"{base_url.rstrip('/')}/analyze", data=body,
            headers={"Content-Type": content_type}, method="POST")
        with urllib.request.urlopen(request, timeout=60) as response:
            import json
            return json.loads(response.read().decode("utf-8"))["risk_band"]
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="text"\r\n\r\n'
        f"{case['text']}\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/analyze",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        import json
        return json.loads(response.read().decode("utf-8"))["risk_band"]


def evaluate(cases, live=False, base_url="http://127.0.0.1:8000"):
    if live:
        predict = lambda case: live_band(case, base_url)
    else:
        domains = set()
        for case in cases:
            scan_text = case["text"]
            if case.get("input_type", "text") == "eml":
                scan_text = (ROOT / scan_text).read_text(encoding="utf-8", errors="ignore")
            domains.update(re.findall(r"[A-Za-z0-9.-]+\.example\b", scan_text.lower()))
        os.environ["DEMO_MODE"] = "1"
        os.environ["DEMO_FIXTURE_DOMAINS"] = ",".join(sorted(domains))
        sys.path.insert(0, str(ROOT))
        predict = local_band

    results = []
    for case in cases:
        results.append({**case, "predicted_band": predict(case)})
    return results


def label_band_status(truth, band):
    if truth == "scam":
        return {
            BANDS[0]: "DANGEROUS MISS",
            BANDS[1]: "ABSTENTION",
            BANDS[2]: "SCAM FLAGGED",
        }[band]
    return {
        BANDS[0]: "LEGITIMATE ALIGNED",
        BANDS[1]: "ABSTENTION",
        BANDS[2]: "FALSE ALARM",
    }[band]


def report(results):
    matrix = {truth: Counter() for truth in ("scam", "legitimate")}
    classes = Counter()
    abstentions = Counter()
    case_types = defaultdict(list)
    dangerous = []
    false_alarms = []
    exact = 0

    for row in results:
        truth, band = row["truth"], row["predicted_band"]
        matrix[truth][band] += 1
        classes[truth] += 1
        if band == BANDS[1]:
            abstentions[truth] += 1
        if truth == "scam" and band == BANDS[0]:
            dangerous.append(row["case_id"])
        if truth == "legitimate" and band == BANDS[2]:
            false_alarms.append(row["case_id"])
        if band == row["expected_band"]:
            exact += 1
        case_types[row["case_type"]].append(row)

    print("Confusion matrix (truth vs predicted risk band; counts)")
    print(f"{'truth':<14} {BANDS[0]:>19} {BANDS[1]:>37} {BANDS[2]:>12}")
    for truth in ("scam", "legitimate"):
        print(f"{truth:<14} {matrix[truth][BANDS[0]]:>19} {matrix[truth][BANDS[1]]:>37} {matrix[truth][BANDS[2]]:>12}")

    print("\nDangerous misses (scam predicted likely legitimate): " + (", ".join(dangerous) or "0"))
    print("False alarms (legitimate predicted high risk): " + (", ".join(false_alarms) or "0"))
    print("Abstention rate by truth class (manual-review band)")
    for truth in ("scam", "legitimate"):
        rate = abstentions[truth] / classes[truth] if classes[truth] else 0.0
        print(f"  {truth}: {abstentions[truth]}/{classes[truth]} ({rate:.1%})")

    print("\nPer-case_type table")
    print(f"{'case_type':<31} {'n':>3} {'likely legitimate':>19} {'manual':>8} {'high risk':>10} {'expected match':>15}")
    for case_type in sorted(case_types):
        group = case_types[case_type]
        counts = Counter(r["predicted_band"] for r in group)
        matches = sum(r["predicted_band"] == r["expected_band"] for r in group)
        print(f"{case_type:<31} {len(group):>3} {counts[BANDS[0]]:>19} {counts[BANDS[1]]:>8} {counts[BANDS[2]]:>10} {matches}/{len(group):>13}")

    print(f"\nLabel-vs-band summary: {len(dangerous)} dangerous miss(es); {len(false_alarms)} false alarm(s)")
    print(f"Expected-vs-actual summary: {exact}/{len(results)} expected-band checks pass")
    print("\nPer-case reconciliation (label-vs-band and expected-vs-actual are separate checks)")
    print(f"{'case_id':<9} {'label':<12} {'actual band':<39} {'label-vs-band':<20} {'expected band':<39} {'expected-vs-actual'}")
    for row in results:
        expected_status = "PASS" if row["predicted_band"] == row["expected_band"] else "MISMATCH"
        label_status = label_band_status(row["truth"], row["predicted_band"])
        print(f"{row['case_id']:<9} {row['truth']:<12} {row['predicted_band']:<39} {label_status:<20} {row['expected_band']:<39} {expected_status}")
    return exact == len(results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="POST cases to a running /analyze API")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="base URL used with --live")
    args = parser.parse_args()
    try:
        results = evaluate(load_cases(), live=args.live, base_url=args.base_url)
        return 0 if report(results) else 1
    except (OSError, urllib.error.URLError, ValueError) as exc:
        print(f"Evaluation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
