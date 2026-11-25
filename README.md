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
`10/minute`. Set `RATE_LIMIT` explicitly to change it.

**Production settings.** Set `ENVIRONMENT=production` and the app refuses to start unless
`INDICATOR_PEPPER` is 32+ characters, `ALLOWED_ORIGINS` lists the real site (no localhost or `*`),
`DATABASE_URL` is PostgreSQL, and rate limiting is on; it also hides `/docs`.
Behind a host's proxy, set `FORWARDED_ALLOW_IPS` (the proxy's address, or `*` on a platform that always sits
behind its own proxy and cannot be reached directly) so each visitor's real address reaches the app; production
start-up requires it. Rate-limit counters are in memory per process: keep one worker, or set
`RATE_LIMIT_STORAGE_URI` (for example a Redis address) to share them. Responses carry security headers and a Content-Security-Policy; set `HSTS_ENABLED=1` only once the site
is served over https. Server access logs (request paths, client addresses) are off unless `ACCESS_LOG=1`.
The Docker image builds the web page in a first stage, installs exact hashed versions from
`requirements.lock` and starts uvicorn with `--no-access-log`. Stored analysis results are deleted after
365 days.

## Registry and report guidance

The service can look up CINs in a local SQLite copy of the official MCA company
master data; it does not contact a remote registry. Obtain the source data from
an official MCA/data.gov.in release, then load it with
`python scripts/load_mca_master.py <source.csv> --db data/mca_master.sqlite3`.

Employer advisories: `ADVISORY_BOT_CONTACT=you@bot.example python scripts/advisory_scraper.py fetch`
writes candidates to `advisory_candidates.json` (git-ignored); review, set `statement` and `approved`, then run
`python scripts/advisory_scraper.py promote advisory_candidates.json`. See docs/JUDGMENT_CALLS.md #17.
Set `MCA_DB_PATH` if the database is stored elsewhere. The matcher checks the
registered name and active status. GSTIN/PAN consistency and a conflict between
an offer's founding-year/age claim and MCA incorporation date can add risk points;
recent incorporation without a contradictory claim is informational only.
GSTIN and CIN location codes are shown as informational context.

No official MCA data is included: the official bulk snapshot requires eKYC and is
future scope. For tests and local evaluation, load your own CSV snapshot with `scripts/load_mca_master.py`.

Sender-authentication results are read only from original `.eml` uploads, not from pasted
text or PDF/image uploads. They are shown for information and failures count against the
sender, but a reported pass is never counted as proof, because the file's headers are
written by whoever made it. For Gmail, open the message, select **⋮ → Download message**,
then upload the downloaded `.eml`. Other inputs still verify only the domain
claimed in the letter. The only available external verification signal is an
active, name-matched CIN in the local MCA database whose company name also matches the
contact domain.
`/analyze` also returns `next_steps` and a concise `complaint_summary` based on
the automated findings; these do not replace an official complaint.

## Community scam reports

With `INDICATOR_PEPPER` configured, `/analyze` can return a signed, single-use
`report_token` and a masked `reportable_indicators` list. It extracts only
scammer-role details: payment destinations in a payment demand, phones in HR
contact lines, and the sender address/domain (From header for `.eml`, contact
line otherwise). Candidate To/Cc/Dear details are excluded. Review the masked
list and send only selected IDs to `POST /report`; no report is saved until the
student supplies `consent: true` and `consent_version: 4` (versions 1 to 3 are
rejected).

The checkbox wording is: “Share these details to warn other job seekers: the
payment and contact details you selected above, and a scrambled fingerprint of
the letter's wording with names and numbers removed. We don't store the letter,
your name or your contact details. You can withdraw this report later with the
code we give you. The public scam-trends page will show these details in masked form
so it can warn other job seekers.” The response gives a one-time withdrawal code for
`POST /report/withdraw`. Report tokens expire after 24 hours. Indicators use
peppered HMAC digests; template matching uses a 128-value MinHash after masking
names and identifiers, amounts, and dates. The service does not store offer
text. Counts affect scoring at 3 reports (+25) and 10 reports (+40); similar
reported templates add +25. These are warning signals, never external
verification, and are not independently verified claims. Details disclose
only “3+ separate reports” or “10+ separate reports”. Reports must span at least
two different days before they count or appear publicly (one burst never does; this is
not proof of independence). `/indicators/stats` returns aggregate counts and suppresses
cells below 5.

Disputes are rate limited and capped (3 open per address, 5 per indicator). An unresolved dispute
lapses after 90 days and is deleted after 180. A dispute does not remove points; its match detail
shows that it is under review. Only a domain dispute verified through a
one-time link sent to that same domain is temporarily excluded from scoring.
Configure SMTP to deliver those links; the code sits in the link's #fragment and is posted in a request body, so it never appears in server logs. Dispute contact email is retained for
12 months after resolution. Reports can be withdrawn with their one-time code;
inactive indicators expire after 24 months.

HMACed identifiers and MinHash signatures are pseudonymised, not anonymous.
The DPDP Act, 2023 and its Rules, including the lawful basis for third-party
sender data, require legal review before deployment. Set `INDICATOR_PEPPER`
from deployment secret storage; do not commit it. `INDICATOR_KEY_VERSION`
versions digests during rotation, and `INDICATOR_PEPPER_PREVIOUS` temporarily
keeps older digests matchable until they expire.

## Public scam-trends page

The page at `/dashboard` (API under `/trends/`) shows aggregate, anonymous trends
for everyone using the site. Every successful `/analyze` call records one anonymous
trend row: ISO week (`YYYY-Www`), risk band and one scam category. No text,
identifiers, file name, company name or IP address is stored with it, and it is not
linked to the analysis or to any report. Rows are deleted 24 months after their
week. Checks are not deduplicated, so counts are checks, not unique people. See
[the privacy design](docs/PRIVACY_DESIGN.md). The page is open and shows only
aggregate data; there is no login and no per-college view.

```powershell
Invoke-RestMethod -Uri http://localhost:8000/trends/dashboard
```

The response contains week-by-band and week-by-category counts for 12 weeks
and a `category_summary` with one row per category: 12-week total, last 4
weeks, previous 8 weeks and a trend word (`Rising`/`Falling`/`Steady`,
comparing the weekly rate of the last 4 weeks with the 8 before them; ±25%),
sorted by total. Every count below five is returned as `"<5"`; a category whose
12-week total is below five gets no trend word and sorts after the others.
`GET /trends/weekly.csv` exports the full weekly data (week × band and
week × category) with the same `<5` rule. It also contains `top_senders`:
masked indicators (type, report count, first and last week, most common
category, dispute status) reported in **3 or more** consented reports, sorted by
count; senders with fewer reports never appear. `GET /trends/senders.csv`
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
- `task_or_chat_scam`: scam-chat wording (paid tasks, pay-to-withdraw, WhatsApp/Telegram-only
  recruiter, no-interview claims) was found and no payment-demand rule above applied.
- `free_mailbox_impersonation`: a failed domain check says the address uses a
  free mailbox or a disposable (temporary) mailbox service.
- `lookalike_domain`: a failed domain check identifies a lookalike or brand.
- `sender_spoofing`: sender authentication fails or adds risk points.
- `no_red_flags`: no check failed and no check added positive risk points.
- `other`: a finding exists but none of the more specific rules applies.

## Tests and migrations

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic check
```

CI runs migrations and tests against PostgreSQL.

## Frontend

The React, TypeScript and Vite interface lives in `frontend/`. Start the API in
one PowerShell window, for example with `docker compose up --build`, and start
the Vite app in another:

```powershell
Set-Location frontend
npm ci
# Optional when the API is not available through the Vite proxy:
# $env:VITE_API_URL = "http://127.0.0.1:8000"
npm run dev
```

**Rollup runs as WebAssembly.** `frontend/package.json` has an npm `overrides`
entry mapping `rollup` to `@rollup/wasm-node` (same version as the Rollup that
Vite resolves), so Vite never loads Rollup's native `.node` binary. That binary
is blocked by Windows Application Control on some PCs, which breaks
`npm run build` and the frontend tests. The WebAssembly build is
a little slower but behaves the same on every platform, including CI. When
upgrading Vite, keep the override's version in step with the Rollup range Vite
requires, then regenerate `package-lock.json`.

Playwright's downloaded Chromium can be blocked by the same policy
(`browserType.launch: spawn UNKNOWN`). Set `PLAYWRIGHT_CHANNEL=msedge` (or
`chrome`) to run the end-to-end tests in an installed, signed browser:

```powershell
$env:PLAYWRIGHT_CHANNEL = "msedge"
npm --prefix frontend run test:e2e
```

Vite proxies backend routes to
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
