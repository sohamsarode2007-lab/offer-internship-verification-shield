"""Load an official MCA company-master CSV into a local SQLite lookup database.

The source CSV must be obtained lawfully from an official MCA/data.gov.in
release. This utility does not download or modify source data.
"""
import argparse
import csv
import sqlite3
from pathlib import Path


ALIASES = {
    "cin": {"cin", "corporateidentificationnumber"},
    "company_name": {"companyname", "nameofcompany"},
    "company_status": {"companystatus", "status"},
    "date_of_registration": {"dateofregistration", "incorporationdate"},
}


def normalized_header(value):
    return "".join(c.lower() for c in value if c.isalnum())


def load_csv(source: Path, destination: Path) -> int:
    with source.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = {normalized_header(name): name for name in (reader.fieldnames or [])}
        selected = {key: next((columns[a] for a in aliases if a in columns), None)
                    for key, aliases in ALIASES.items()}
        missing = [key for key in ("cin", "company_name", "company_status") if not selected[key]]
        if missing:
            raise ValueError("MCA CSV is missing required columns: " + ", ".join(missing))
        destination.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(destination) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS mca_companies (
                cin TEXT PRIMARY KEY, company_name TEXT NOT NULL,
                company_status TEXT NOT NULL, date_of_registration TEXT)""")
            count = 0
            for row in reader:
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
            db.commit()
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path, help="official MCA company master CSV")
    parser.add_argument("--db", type=Path, default=Path("data/mca_master.sqlite3"),
                        help="destination SQLite DB (default: data/mca_master.sqlite3)")
    args = parser.parse_args()
    count = load_csv(args.csv_path, args.db)
    print(f"Loaded or updated {count} MCA company rows in {args.db}")


if __name__ == "__main__":
    main()
