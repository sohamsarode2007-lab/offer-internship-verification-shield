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

No official MCA data is included: the official bulk snapshot requires eKYC and is
future scope. For demos, `fixtures/demo/synthetic_mca_master.csv` holds fictional
companies; load it with `--synthetic` (stored as `source=SYNTHETIC`, used only when
`DEMO_MODE=1`). See [fixture notes](fixtures/demo/README.md#synthetic-company-registry).

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

## Community scam reports

With `INDICATOR_PEPPER` configured, `/analyze` can return a signed, single-use
`report_token` and a masked `reportable_indicators` list. It extracts only
scammer-role details: payment destinations in a payment demand, phones in HR
contact lines, and the sender address/domain (From header for `.eml`, contact
line otherwise). Candidate To/Cc/Dear details are excluded. Review the masked
list and send only selected IDs to `POST /report`; no report is saved until the
student supplies `consent: true` and `consent_version: 2`.

The checkbox wording is: “Share these details to warn other students: the
payment and contact details you selected above, and a scrambled fingerprint of
the letter's wording with names and numbers removed. We don't store the letter,
your name or your contact details. You can withdraw this report later with the
code we give you.” The response gives a one-time withdrawal code for
`POST /report/withdraw`. Report tokens expire after 24 hours. Indicators use
peppered HMAC digests; template matching uses a 128-value MinHash after masking
names and identifiers, amounts, and dates. The service does not store offer
text. Counts affect scoring at 3 reports (+25) and 10 reports (+40); similar
reported templates add +25. These are warning signals, never external
verification, and are not independently verified claims. Details disclose
only “3+ students” or “10+ students”. `/indicators/stats` returns aggregate
counts and suppresses cells below 5.

Disputes are rate limited. A dispute does not remove points; its match detail
shows that it is under review. Only a domain dispute verified through a
one-time link sent to that same domain is temporarily excluded from scoring.
Configure SMTP to deliver those links. Dispute contact email is retained for
12 months after resolution. Reports can be withdrawn with their one-time code;
inactive indicators expire after 24 months. Demo reports can be seeded only
with `DEMO_MODE=1` using `python scripts/seed_demo_reports.py`; they count only
in demo mode.

HMACed identifiers and MinHash signatures are pseudonymised, not anonymous.
The DPDP Act, 2023 and its Rules, including the lawful basis for third-party
sender data, require legal review before deployment. Set `INDICATOR_PEPPER`
from deployment secret storage; do not commit it. `INDICATOR_KEY_VERSION`
versions digests during rotation, and `INDICATOR_PEPPER_PREVIOUS` temporarily
keeps older digests matchable until they expire.

## Placement-cell dashboard

Run migrations, then add an institution from an administrative shell:

```powershell
python -m alembic upgrade head
python scripts/add_institution.py --name "Example College" --code EXAMPLE
```

The CLI prints a random API key once. Store it as a secret; the database keeps
only its SHA-256 hash. `/analyze` accepts an optional `institution_code` form
field. A matching code records only the institution ID, ISO week (`YYYY-Www`),
risk band, and one scam category. Unknown codes are silently ignored. The offer
text, name, contacts, registration values, and analysis checks are not copied to
the institution trend tables.
These are consented submissions attributed by the supplied code; enrollment is
not independently verified and repeated submissions are not deduplicated by
student.

Read the latest 12 weeks with the institution key in `X-API-Key`:

```powershell
Invoke-RestMethod -Uri http://localhost:8000/institutions/me/dashboard `
  -Headers @{ "X-API-Key" = "PASTE_KEY_STORED_SECURELY" }
```

The response contains week-by-band and week-by-category counts; any cell below
five is returned as `"<5"`. The endpoint is limited to 30 requests per minute.
Category rules use the existing check results and follow this priority:

- `security_deposit`: a payment demand mentions a deposit.
- `training_or_kit_fee`: a payment demand mentions training, kit, laptop,
  onboarding, document, or background charges.
- `fake_government_scheme`: a payment demand co-occurs with government, govt,
  ministry, or department scheme wording.
- `registration_fee`: a registration, application, processing, joining, or
  verification fee demand not classified above.
- `free_mailbox_impersonation`: a failed domain check says the address uses a
  free mailbox.
- `lookalike_domain`: a failed domain check identifies a lookalike or brand.
- `sender_spoofing`: sender authentication fails or adds risk points.
- `no_red_flags`: no check failed and no check added positive risk points.
- `other`: a finding exists but none of the more specific rules applies.

## Tests and migrations

```powershell
..\.venv\Scripts\python.exe -m pytest -q
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m alembic check
```

CI runs migrations and tests against PostgreSQL.

## Frontend

The React, TypeScript and Vite interface lives in `frontend/`. Start the API in
one PowerShell window, for example with `docker compose up --build`, and start
the Vite app in another:

```powershell
Set-Location frontend
npm ci
$env:VITE_DEMO = "1"
# Optional when the API is not available through the Vite proxy:
# $env:VITE_API_URL = "http://127.0.0.1:8000"
npm run dev
```

`VITE_DEMO=1` shows the three fictional text samples from `fixtures/demo/`;
otherwise the sample row is hidden. Vite proxies backend routes to
`http://127.0.0.1:8000`. The default backend `ALLOWED_ORIGINS` includes the Vite
origin `http://127.0.0.1:5173` and `http://localhost:5173`.

Create the production assets with:

```powershell
Set-Location frontend
npm ci
npm run build
Set-Location ..
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The API serves only `frontend/dist` when its built `index.html` exists, with
client-route fallback to that built index. It never serves the unbuilt Vite
source page.
