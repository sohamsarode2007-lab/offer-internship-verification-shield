"""Print how old each local data source is, and what to do about it. Reads local files only; no network.

    python -m scripts.upkeep_report            # exit 0 if every source is current, 1 otherwise

A source is "stale" when older than the thresholds in app/services/source_freshness.py (company snapshot 90 days,
employer advisories 180 days) and "unknown" when it has no date. Run it monthly; docs/DATA_UPKEEP.md has the steps.
"""
import sys

from app.services.source_freshness import build_sources

ACTIONS = {
    "company_registry": "Refresh the snapshot: see 'Company register snapshot' in docs/DATA_UPKEEP.md.",
    "employer_advisories": "Re-read each advisory page by hand and update its 'retrieved' date: see docs/DATA_UPKEEP.md.",
}


def main() -> int:
    needs_action = 0
    for source in build_sources()["sources"]:
        age = source.get("age_days")
        print(f"[{source['status'].upper():7}] {source['name']}: "
              f"{'no date' if age is None else f'{age} days old'}. {source.get('detail', '')}")
        if source["status"] != "current":
            needs_action += 1
            print(f"          -> {ACTIONS.get(source['id'], 'See docs/DATA_UPKEEP.md.')}")
    return 1 if needs_action else 0


if __name__ == "__main__":
    sys.exit(main())
