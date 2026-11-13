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
        if case.get("expected_band") not in BANDS:
            raise ValueError(f"{case.get('case_id')}: unsupported expected band")
    return cases


def local_band(text):
    # Synthetic .example domains are configured as demo fixtures to keep this path
    # offline and deterministic. No external DNS or registry calls are made.
    from app.services import domain_verification, fact_extraction, gstin_verification
    from app.services import payment_detection, risk_scoring

    facts = fact_extraction.extract_facts(text)
    checks = [
        domain_verification.verify_domain(facts),
        gstin_verification.verify_gstin(facts),
        payment_detection.detect_payment_demand(facts),
    ]
    return risk_scoring.calculate_risk_score(checks, facts=facts)["risk_band"]


def live_band(text, base_url):
    boundary = "----CodexEvalBoundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="text"\r\n\r\n'
        f"{text}\r\n"
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
        predict = lambda text: live_band(text, base_url)
    else:
        domains = set()
        for case in cases:
            domains.update(re.findall(r"[A-Za-z0-9.-]+\.example\b", case["text"].lower()))
        os.environ["DEMO_MODE"] = "1"
        os.environ["DEMO_FIXTURE_DOMAINS"] = ",".join(sorted(domains))
        sys.path.insert(0, str(ROOT))
        predict = local_band

    results = []
    for case in cases:
        results.append({**case, "predicted_band": predict(case["text"])})
    return results


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

    print(f"\nExpected-band regression matches: {exact}/{len(results)}")
    for row in results:
        print(f"  {row['case_id']} [{row['truth']}/{row['case_type']}]: {row['predicted_band']} (expected {row['expected_band']})")
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
