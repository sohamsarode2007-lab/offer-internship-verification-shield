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
student supplies `consent: true` and `consent_version: 3` (versions 1 and 2 are
rejected).

The checkbox wording is: “Share these details to warn other students: the
payment and contact details you selected above, and a scrambled fingerprint of
the letter's wording with names and numbers removed. We don't store the letter,
your name or your contact details. You can withdraw this report later with the
code we give you. VIT's placement cell will see these details in masked form so
it can warn other students.” The response gives a one-time withdrawal code for
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
inactive indicators expire after 24 months. Simulated VIT Pune reports (8
fictional senders in `fixtures/demo/vit_simulated_senders.csv`, 45 reports over
12 weeks) can be seeded only with `DEMO_MODE=1` using
`python scripts/seed_demo_reports.py` (idempotent; `run_demo.bat` runs it); they
are flagged demo and count only in demo mode. The same script seeds 484
simulated checks with the same three fields every real check records (week,
band, category) so the demo's 12-week chart and category summary are populated.

HMACed identifiers and MinHash signatures are pseudonymised, not anonymous.
The DPDP Act, 2023 and its Rules, including the lawful basis for third-party
sender data, require legal review before deployment. Set `INDICATOR_PEPPER`
from deployment secret storage; do not commit it. `INDICATOR_KEY_VERSION`
versions digests during rotation, and `INDICATOR_PEPPER_PREVIOUS` temporarily
keeps older digests matchable until they expire.

## VIT Pune placement cell (single-college simulation)

This build simulates one college, **VIT Pune**. Its institution record is
created automatically; there are no college codes or API keys. Every
successful `/analyze` call records one anonymous trend row for VIT Pune: ISO
week (`YYYY-Www`), risk band and one scam category. No text, identifiers, file
name, company name or IP address is stored with it, and it is not linked to the
analysis or to any report. Rows are deleted 24 months after their week. Checks
are not deduplicated by student and enrollment is not verified, so counts are
checks, not unique students. See [the privacy design](docs/PRIVACY_DESIGN.md).

Multiple colleges and a staff login for this page are future scope; until then
the page is open and shows only aggregate data.

```powershell
Invoke-RestMethod -Uri http://localhost:8000/placement-cell/dashboard
```

The response contains week-by-band and week-by-category counts for 12 weeks
and a `category_summary` with one row per category: 12-week total, last 4
weeks, previous 8 weeks and a trend word (`Rising`/`Falling`/`Steady`,
comparing the weekly rate of the last 4 weeks with the 8 before them; ±25%),
sorted by total. Every count below five is returned as `"<5"`; a category whose
12-week total is below five gets no trend word and sorts after the others.
`GET /placement-cell/weekly.csv` exports the full weekly data (week × band and
week × category) with the same `<5` rule. It also contains `top_senders`:
masked indicators (type, report count, first and last week, most common
category, dispute status) reported in **3 or more** consented reports, sorted by
count; senders with fewer reports never appear. `GET /placement-cell/senders.csv`
exports the same list as the "warning list". Only masked forms are stored and
shown; a non-free-mail sender domain is shown in full. See
[the privacy design](docs/PRIVACY_DESIGN.md). Both endpoints are limited to 30
requests per minute.
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

`VITE_DEMO=1` shows the fictional text samples from `fixtures/demo/`;
otherwise the sample row is hidden.

**Rollup runs as WebAssembly.** `frontend/package.json` has an npm `overrides`
entry mapping `rollup` to `@rollup/wasm-node` (same version as the Rollup that
Vite resolves), so Vite never loads Rollup's native `.node` binary. That binary
is blocked by Windows Application Control on some PCs, which breaks
`npm run build`, the frontend tests and `run_demo.bat`. The WebAssembly build is
a little slower but behaves the same on every platform, including CI. When
upgrading Vite, keep the override's version in step with the Rollup range Vite
requires, then regenerate `package-lock.json`.

Playwright's downloaded Chromium can be blocked by the same policy
(`browserType.launch: spawn UNKNOWN`). Set `PLAYWRIGHT_CHANNEL=msedge` (or
`chrome`) to run the end-to-end tests in an installed, signed browser:

```powershell
$env:PLAYWRIGHT_CHANNEL = "msedge"
npm --prefix frontend run test:e2e
``` Vite proxies backend routes to
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
