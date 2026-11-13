# Offer & Internship Verification Shield

FastAPI backend for rule-based checks of Indian job and internship offers. The
`rule_based_v2` score combines domain and registration checks with payment-demand
detection. It does not use a production ML model.

## Local setup

Copy `.env.example` to `.env`, configure the database values, then start the API:

```powershell
Copy-Item .env.example .env
docker compose up --build
```

The API accepts text or PDF/image/email (`.eml`) uploads at `POST /analyze`.
OCR uploads need Tesseract; scanned PDFs also need Poppler. The CI workflow installs both.

## Rate limit

`RATE_LIMIT` controls the per-IP API limit in SlowAPI syntax, and defaults to
`10/minute`. When `DEMO_MODE=1` and `RATE_LIMIT` is unset, the default is
`100/minute`. Set `RATE_LIMIT` explicitly to override either default.

## Demo fixtures

The synthetic demo includes two fictional company domains and a fictional
government-scheme scam example. Set `DEMO_MODE=1` and
`DEMO_FIXTURE_DOMAINS=emberlakeanalytics.example,brightpathedtech.example` to
exercise the labelled domain fixtures. See [fixture notes](fixtures/demo/README.md).

## Registry and report guidance

The service can look up CINs in a local SQLite copy of the official MCA company
master data; it does not contact a remote registry. Obtain the source data from
an official MCA/data.gov.in release, then load it with
`python scripts/load_mca_master.py <source.csv> --db data/mca_master.sqlite3`.
Set `MCA_DB_PATH` if the database is stored elsewhere. The matcher checks the
registered name and active status. GSTIN/PAN consistency and a conflict between
an offer's founding-year/age claim and MCA incorporation date can add risk points;
recent incorporation without a contradictory claim is informational only.
GSTIN and CIN location codes are shown as informational context.

Sender authentication using DMARC and aligned DKIM is available only for
original `.eml` uploads, not for pasted text or PDF/image uploads. It checks the
topmost `Authentication-Results` supplied by the receiving mail provider and the
actual From domain. For Gmail, open the message, select **⋮ → Download message**,
then upload the downloaded `.eml`. Other inputs still verify only the domain
claimed in the letter. The only available external verification signals are an
active, name-matched CIN in the local MCA database or an aligned authenticated
sender from an `.eml`.
`/analyze` also returns `next_steps` and a concise `complaint_summary` based on
the automated findings; these do not replace an official complaint.

## Tests and migrations

```powershell
..\.venv\Scripts\python.exe -m pytest -q
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m alembic check
```

CI runs migrations and tests against PostgreSQL.
