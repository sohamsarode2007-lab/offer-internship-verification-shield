"""
What the checks are built on and how old it is, for the public "data sources" panel (no secrets, no offer data).

Each source reports a date and an age in days, and is flagged "stale" past a threshold so people (and the operator)
can see when a snapshot needs refreshing. A source with no date is reported as "unknown", never as fresh.
"""
import os
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.services import brand_advisories, link_lookup, request_budget
from app.services.risk_scoring import SCORING_MODEL

REGISTRY_STALE_DAYS = 90
ADVISORY_STALE_DAYS = 180


def _age_days(day: Optional[date], today: date) -> Optional[int]:
    return (today - day).days if day else None


def _parse(value: Optional[str]) -> Optional[date]:
    try:
        return datetime.fromisoformat(value).date() if value else None
    except ValueError:
        return None


def _registry(today: date) -> Dict[str, Any]:
    entry: Dict[str, Any] = {"id": "company_registry", "name": "Company registry snapshot (local copy)",
                             "updated": None, "age_days": None, "status": "unknown", "detail": "No registry snapshot is loaded."}
    path = Path(os.getenv("MCA_DB_PATH", "data/mca_master.sqlite3"))
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path
    if not path.is_file():
        return entry
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
            meta = dict(db.execute("SELECT key, value FROM registry_metadata").fetchall())
    except sqlite3.Error:
        entry["detail"] = "A registry file exists but has no load date."
        return entry
    loaded = _parse(meta.get("loaded_at"))
    label = (meta.get("source") or "unlabelled").upper()
    entry.update(updated=loaded.isoformat() if loaded else None, age_days=_age_days(loaded, today),
                 detail=f"Source label {label}, {meta.get('row_count', '?')} companies.")
    if label == "SYNTHETIC":
        entry["status"] = "unknown"
        entry["detail"] += " This file is marked as made-up data, so it is ignored."
    elif loaded:
        entry["status"] = "stale" if entry["age_days"] > REGISTRY_STALE_DAYS else "current"
    return entry


def _advisories(today: date) -> Dict[str, Any]:
    dates = [d for d in (_parse(a.get("retrieved")) for a in brand_advisories.load_advisories()) if d]
    oldest = min(dates) if dates else None
    age = _age_days(oldest, today)
    return {"id": "employer_advisories", "name": "Employer fraud advisories (read by hand)",
            "updated": oldest.isoformat() if oldest else None, "age_days": age,
            "status": "unknown" if age is None else "stale" if age > ADVISORY_STALE_DAYS else "current",
            "detail": f"{len(brand_advisories.load_advisories())} employers; the date shown is the oldest page read."}


def build_sources(today: Optional[date] = None) -> Dict[str, Any]:
    today = today or datetime.now(timezone.utc).date()
    sources: List[Dict[str, Any]] = [_registry(today), _advisories(today)]
    budgets = [{"id": name, "used_today": request_budget.used(name), "daily_limit": request_budget.limit(name)}
               for name in request_budget.DEFAULTS]
    return {
        "scoring_model": SCORING_MODEL,
        "sources": sources,
        "optional_lookups": {
            "link_lookups": link_lookup.is_enabled(),
            "web_risk_key_set": bool(os.getenv("WEB_RISK_API_KEY")),
            "live_registry": bool(os.getenv("DATA_GOV_IN_API_KEY")),
            "domain_age_archive": os.getenv("INFRA_AGE_LOOKUPS") == "1",
            "careers_page": os.getenv("CAREERS_PAGE_LOOKUPS") == "1",
        },
        "request_budgets": budgets,
    }
