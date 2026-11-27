"""Load a company-master CSV into a local SQLite lookup database.

Official data: the source CSV must be obtained lawfully from an official MCA
release. This utility does not download or modify source data.

Safety rules:
  - A CSV with rows marked Synthetic=true (made-up companies) is always refused.
  - A database previously labelled SYNTHETIC is never updated; delete it and reload.
"""
import argparse
import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


ALIASES = {
    "cin": {"cin", "corporateidentificationnumber"},
    "company_name": {"companyname", "nameofcompany"},
    "company_status": {"companystatus", "status"},
    # "companyregistrationdatedate" is the data.gov.in column (CompanyRegistrationdate_date).
    "date_of_registration": {"dateofregistration", "incorporationdate", "companyregistrationdatedate"},
    "synthetic": {"synthetic"},
}

SOURCE_SYNTHETIC = "SYNTHETIC"
SOURCE_MCA_CSV = "MCA_CSV"
TRUE_VALUES = {"true", "1", "yes", "y"}


def normalized_header(value):
    return "".join(c.lower() for c in value if c.isalnum())


def _existing_source(db: sqlite3.Connection):
    has_rows = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='mca_companies'").fetchone()
    has_meta = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='registry_metadata'").fetchone()
    if has_meta:
        row = db.execute("SELECT value FROM registry_metadata WHERE key='source'").fetchone()
        if row:
            return row[0]
    if has_rows and db.execute("SELECT 1 FROM mca_companies LIMIT 1").fetchone():
        return SOURCE_MCA_CSV  # legacy database created before metadata existed
    return None


def load_csv(source: Path, destination: Path) -> int:
    source_label = SOURCE_MCA_CSV
    with source.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = {normalized_header(name): name for name in (reader.fieldnames or [])}
        selected = {key: next((columns[a] for a in aliases if a in columns), None)
                    for key, aliases in ALIASES.items()}
        missing = [key for key in ("cin", "company_name", "company_status") if not selected[key]]
        if missing:
            raise ValueError("Company-master CSV is missing required columns: " + ", ".join(missing))
        rows = list(reader)

    marked_synthetic = selected["synthetic"] and any(
        (row.get(selected["synthetic"]) or "").strip().lower() in TRUE_VALUES for row in rows)
    if marked_synthetic:
        raise ValueError("This CSV contains rows marked Synthetic=true (made-up companies); refusing to load it.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(destination) as db:
        existing = _existing_source(db)
        if existing and existing != source_label:
            raise ValueError(
                f"{destination} already holds {existing} data; refusing to mix it with {source_label} rows. "
                "Use a different --db path.")
        db.execute("""CREATE TABLE IF NOT EXISTS mca_companies (
            cin TEXT PRIMARY KEY, company_name TEXT NOT NULL,
            company_status TEXT NOT NULL, date_of_registration TEXT)""")
        db.execute("CREATE TABLE IF NOT EXISTS registry_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        count = 0
        for row in rows:
            cin = (row.get(selected["cin"]) or "").strip().upper()
            name = (row.get(selected["company_name"]) or "").strip()
            status = (row.get(selected["company_status"]) or "").strip()
            if not cin or not name or not status:
                continue
            date = (row.get(selected["date_of_registration"]) or "").strip() if selected["date_of_registration"] else ""
            db.execute("""INSERT INTO mca_companies
                (cin, company_name, company_status, date_of_registration) VALUES (?, ?, ?, ?)
                ON CONFLICT(cin) DO UPDATE SET company_name=excluded.company_name,
                company_status=excluded.company_status,
                date_of_registration=excluded.date_of_registration""",
                (cin, name, status, date or None))
            count += 1
        metadata = {
            "source": source_label,
            "loaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "row_count": str(db.execute("SELECT COUNT(*) FROM mca_companies").fetchone()[0]),
        }
        db.executemany("INSERT INTO registry_metadata (key, value) VALUES (?, ?) "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value", metadata.items())
        db.commit()
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv_path", type=Path, help="company-master CSV")
    parser.add_argument("--db", type=Path, default=Path("data/mca_master.sqlite3"),
                        help="destination SQLite DB (default: data/mca_master.sqlite3)")
    args = parser.parse_args()
    count = load_csv(args.csv_path, args.db)
    print(f"Loaded or updated {count} company rows in {args.db}")


if __name__ == "__main__":
    main()
