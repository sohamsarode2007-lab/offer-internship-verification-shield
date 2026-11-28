"""Run the hand-written regression cases (made-up offers, test-only) through local rules or a live API."""

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
        if case.get("input_type", "text") not in {"text", "text_file", "eml"}:
            raise ValueError(f"{case.get('case_id')}: unsupported input_type")
        if case.get("expected_band") not in BANDS:
            raise ValueError(f"{case.get('case_id')}: unsupported expected band")
        if not case.get("expected_basis"):
            raise ValueError(f"{case.get('case_id')}: expected_basis must record the hand calculation")
    return cases


def case_text(case):
    """Inline text, or the contents of a repo-relative fixture file (input_type=text_file)."""
    if case.get("input_type", "text") == "text_file":
        return (ROOT / case["text"]).read_text(encoding="utf-8")
    return case["text"]


_REGISTRY_DB = None


def _synthetic_registry_db():
    """Load the test-only company list (fictional companies) into a temporary SQLite file."""
    global _REGISTRY_DB
    if _REGISTRY_DB is None:
        import tempfile
        sys.path.insert(0, str(ROOT))
        from scripts.load_mca_master import load_csv
        _REGISTRY_DB = Path(tempfile.mkdtemp(prefix="eval-registry-")) / "test-registry.sqlite3"
        load_csv(ROOT / "tests" / "fixtures" / "offers" / "company_registry.csv", _REGISTRY_DB)
    return _REGISTRY_DB


def _mock_dns(domains):
    """Offline DNS for the eval: the cases' .example domains publish MX/SPF/DMARC, all else is NXDOMAIN."""
    import dns.resolver
    sys.path.insert(0, str(ROOT))
    from app.services import domain_verification as dv

    class _Txt:
        def __init__(self, value):
            self.strings = [value.encode()]

    def resolve(name, rtype):
        host = str(name).lower().rstrip(".")
        base = host[len("_dmarc."):] if host.startswith("_dmarc.") else host
        if base not in domains:
            raise dns.resolver.NXDOMAIN()
        if rtype == "MX" and base == host:
            return [object()]
        if rtype == "TXT":
            return [_Txt("v=DMARC1; p=reject" if host.startswith("_dmarc.") else "v=spf1 -all")]
        raise dns.resolver.NoAnswer()

    dv._resolver.resolve = resolve
    dv._whois_creation_date = lambda domain: None
    dv._rdap_creation_date = lambda domain: None


def local_band(case):
    # The made-up .example domains answer from mocked DNS (see _mock_dns) to keep this path
    # offline and deterministic. No external DNS or registry calls are made.
    from app.services import domain_verification, fact_extraction, gstin_verification
    from app.services import payment_detection, risk_scoring, scam_text

    from app.services import email_auth, ingestion, community_reports
    if case.get("community_fixture"):
        os.environ.setdefault("INDICATOR_PEPPER", "eval-only-pepper")
        os.environ.setdefault("INDICATOR_KEY_VERSION", "1")
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
        payment_check = payment_detection.detect_payment_demand(facts)
        indicators = community_reports.extract_indicators(text, parsed, payment_check)
    else:
        text = case_text(case)
        facts = fact_extraction.extract_facts(text)
        domain_check = domain_verification.verify_domain(facts)
        auth_check = email_auth.not_applicable()
        payment_check = payment_detection.detect_payment_demand(facts)
        indicators = community_reports.extract_indicators(text, None, payment_check)
    signature = community_reports.minhash_signature(text) if os.getenv("INDICATOR_PEPPER") else []
    community_check = community_reports.lookup_community(
        _seed_eval_community(case, community_reports) if case.get("community_fixture") else _empty_eval_db(),
        indicators, signature)
    checks = [domain_check, gstin_verification.verify_gstin(facts), payment_check, auth_check,
              scam_text.detect_scam_text(facts), community_check]
    return risk_scoring.calculate_risk_score(checks, facts=facts)["risk_band"]


_EVAL_DB = None


def _new_eval_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.db.database import Base
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _empty_eval_db():
    global _EVAL_DB
    if _EVAL_DB is None:
        _EVAL_DB = _new_eval_db()
    return _EVAL_DB


def _seed_eval_community(case, community_reports):
    from datetime import timedelta
    from app.services.fact_extraction import extract_facts
    from app.services.payment_detection import detect_payment_demand
    db = _new_eval_db()
    fixture = ("No registration number is shown. Contact HR at hr@fraud.example or WhatsApp +91 9123456001. "
               "This remote role requires a processing fee of Rs 500 to rky.verma@ybl. "
               "We are pleased to offer the analyst internship. Please confirm your joining date and reply "
               "to the recruitment team. The role includes training, weekly meetings, and project work with "
               "our engineering group.")
    for idx in range(3):
        facts = extract_facts(fixture)
        indicators = community_reports.extract_indicators(fixture, None, detect_payment_demand(facts))
        signature = community_reports.minhash_signature(fixture)
        token, _ = community_reports.issue_report_token(db, indicators, signature)
        selected = [x["indicator_type"] + ":" + x["digest"] for x in indicators]
        community_reports.accept_report(db, token, selected, True, community_reports.CONSENT_VERSION)
        if idx == 0:
            for row in db.query(community_reports.CommunityReport).all():
                row.created_at = row.created_at - timedelta(days=1)
            db.commit()
    return db


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
        f"{case_text(case)}\r\n"
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
            if case.get("input_type", "text") in {"eml", "text_file"}:
                scan_text = (ROOT / scan_text).read_text(encoding="utf-8", errors="ignore")
            domains.update(re.findall(r"[A-Za-z0-9.-]+\.example\b", scan_text.lower()))
        _mock_dns(domains)
        # Cases flagged registry_fixture=true run against the test-only company list.
        # Every other case sees no registry at all.
        if any(case.get("registry_fixture", "").lower() == "true" for case in cases):
            os.environ["MCA_DB_PATH"] = str(_synthetic_registry_db())
        else:
            os.environ["MCA_DB_PATH"] = str(ROOT / "eval" / "no-registry.sqlite3")
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
    unknown = [c for c in dangerous if c not in KNOWN_DANGEROUS_MISSES]
    if unknown:
        print("\nFAIL: new dangerous miss(es) (a scam rated likely legitimate): " + ", ".join(unknown)
              + ". Fix the rule; do not add to KNOWN_DANGEROUS_MISSES to make this pass.")
    return exact == len(results) and not unknown


# Documented limit, kept visible on purpose (CLAIMS.md, 'What it cannot catch'). Any other scam rated likely legitimate
# fails the run.
KNOWN_DANGEROUS_MISSES = {"EC41"}


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
