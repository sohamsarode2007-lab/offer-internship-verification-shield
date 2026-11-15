# Capability claims and verification status

This file records what the current implementation actually checks and what has
been verified in this workspace.

## Data provenance and evaluation

- The prior `legit_offers_raw.csv`, `reddit_scams_raw.csv`,
  `benchmark_dataset_v1.csv`, `scam_dataset.csv`, and old `synthetic_scam.csv`
  are quarantined locally under `data/quarantine/`. Their CSVs are Git-ignored;
  `data/quarantine/MANIFEST.md` records their SHA-256 hashes.
- The old legitimate class was not a collection of Indian offer letters. It had
  151 Arbeitnow, 50 Jobicy, and 18 Remotive rows plus 12 agent-written templates
  in the benchmark (176/50/18 plus the same 12 templates in the raw legit file).
  The templates used invented URLs. A fixed-seed hand review found concrete
  scam descriptions in 5 of 30 sampled Reddit rows. Literal `...` truncation
  affected 203/261 ConsumerComplaints rows in the scrape and 196/254 in the
  benchmark. See `data/quarantine/README.md` for audit details and method.
- Those labels and source/geography imbalances do not support a credible
  real-world classifier accuracy claim. No real evaluation set is included.
  `eval/edge_cases.csv` is synthetic regression data only; its output is not a
  real-world performance estimate.
- `data/synthetic_scam.csv` is the regenerated 50-row synthetic corpus. All rows
  are marked `synthetic=true`; the free-mailbox/GSTIN-format examples use
  fictional `.example` domains and checksum-generated GSTINs.

## Demo mode

- The demo uses `DEMO_MODE` fixtures for two fictional domains:
  `emberlakeanalytics.example` and `brightpathedtech.example`. Fixture results are
  labelled in the output as `[DEMO FIXTURE — not a live DNS result]`; they are not
  live DNS or company registry results.
- The government-scheme document is also fictional and is labelled as a sample
  scam pattern in its source text.
- **The demo company registry is synthetic.** `fixtures/demo/synthetic_mca_master.csv`
  lists 13 fictional companies (invented names, made-up CINs in the real CIN format;
  active, struck-off, dissolved and under-liquidation statuses). Loaded with
  `scripts/load_mca_master.py --synthetic`, the database records `source=SYNTHETIC`
  and the app consults it only when `DEMO_MODE=1`; outside demo mode it behaves as if
  no registry is loaded. This demonstrates the full pipeline (CSV → loader → SQLite →
  CIN lookup → scoring) with fictional data only.
- In demo mode, synthetic registry results are displayed like any registry result,
  **without a synthetic label on the website**: the details read
  `Company registry match: <name>; Active; incorporated <date>.` for an active,
  name-matched company; failures lead with the problem: `Company is <status> in
  company registry records: <name>; incorporated <date>.` or `CIN belongs to a
  different company in company registry records: ...`. The same wording is used for
  real company-master data. No UI
  text, API detail or page describes this data as official, live, MCA data or from
  data.gov.in. Every such response carries the non-displayed API field
  `registry_source: "synthetic"`, so a result can always be traced to the synthetic
  snapshot. Presenters should state in the demo that the companies are fictional.
- No company-master data is included in this repository. Two optional sources can
  answer a CIN lookup, and each response carries the non-displayed field
  `registry_source`: `mca_csv` (a CSV the operator loaded locally with
  `scripts/load_mca_master.py`) or `ogd` (one lookup by CIN against the
  data.gov.in "RoC-wise Company Master Data" resource, made only when the operator
  sets `DATA_GOV_IN_API_KEY` and DEMO_MODE is off). That resource is a periodically
  refreshed snapshot published under the Government Open Data License - India
  (attribution: Ministry of Corporate Affairs, data.gov.in), not a live registry;
  a company may have changed status since. If the API times out, is blocked or
  returns an unexpected payload the lookup reports "registry not checked", never
  "not found". A CIN absent from the snapshot is `insufficient_information`, not
  evidence against the company. Only CIN, name, status and registration date are
  read; addresses, capital and industry fields are discarded. The registry
  industry-classification column is not used because a sample row for a large
  IT-services company carried an unrelated manufacturing classification.
- Company-name comparison expands legal suffixes (`Pvt.`/`Ltd.` to `Private`/
  `Limited`) before matching, and registry statuses meaning not operating
  (strike off, dissolved, liquidation, amalgamated) fail the check; `Dormant` does not.

## Payment detection and scoring

- Payment detection uses phrase rules and UPI payment context. A nearby UPI VPA
  (within 200 characters of an already-detected, non-negated demand phrase) is
  reported as `UPI payment instruction: <vpa>` in the payment check details.
- Stipend, salary, and reimbursement context remains excluded from standalone UPI
  payment-demand detection. Negated fee phrases are not treated as demands.
- The payment-demand signal is worth 65 points, with urgency near the demand worth
  20 additional points. A payment demand forces a high-risk score of at least 61.
  See the scoring table in `app/services/risk_scoring.py`.
- Payment detection also matches disguised fee names (BGV, certificate, courier-insurance,
  slot/seat booking, ID-card, interview, bond-notarisation, medical-test and similar
  fees), amount-first phrasing ("Rs 4,500 is payable"), "pay 2000 rupees", and a small
  set of Hinglish phrasings ("fees bharna hoga", "500 rupaye bhejiye"). These patterns
  are hand-written, were checked only against hand-written synthetic sentences
  (`tests/test_payment_euphemisms.py`) and carry the same negation handling as the
  original rules; they are not validated on real-world messages. They are skipped
  when the sentence says the company bears the cost or the fee is waived.
- **Known limitation:** urgency without a detected payment demand adds no points.
  Synthetic case EC08 remains labelled `scam` but is now `insufficient evidence,
  verify manually`: its deadline alone is not weighted, and it lacks an external
  verification signal. Its dangerous-miss count is now zero because it is no
  longer rated likely legitimate. This synthetic label is not independent proof
  that a real offer deadline is fraudulent.
- The low-risk band requires a passing domain, a present non-failing identifier,
  and an externally verified signal. The available live external signal is an
  active, name-matched CIN from the locally loaded MCA SQLite master data, or a
  sender authenticated from an original `.eml` by DMARC pass and aligned DKIM.
  The latter verifies the sender as recorded by the recipient's mail provider;
  it does not establish who authored the message. Structural domain/GSTIN checks
  alone are capped at manual review. The demo registry fixture is an explicit
  demo-only exception for illustrating that path; it is not external verification.
- `scripts/load_mca_master.py` imports a company-master CSV into local SQLite and
  records its source (`MCA_CSV`, or `SYNTHETIC` with `--synthetic`). Rows marked
  `Synthetic=true` are refused without `--synthetic`, and the two sources are never
  mixed in one database. This workspace does not include official MCA data (future
  scope, eKYC required); lookup behaviour is tested with temporary database rows
  and the synthetic demo snapshot.
- `/analyze` returns `next_steps` and `complaint_summary` based on its rule
  results. These are automated guidance, not an official complaint filing.
  High-risk results tell people who already paid to call the National Cyber
  Crime Helpline 1930 and report at cybercrime.gov.in. `/analyze` also returns
  `reasons`: the same rules as `risk_factors`, worded for people with each
  rule's score impact. A report (and its token) is offered only for high risk
  and insufficient evidence, never for a likely-legitimate result.
- Sender authentication is available only for `.eml` uploads. It reads the
  topmost Authentication-Results header and does not store or log headers.
  Pasted text, PDFs, and images still check only the domain claimed in the content.
- **Community indicator network is implemented.** `/analyze` offers a signed
  24-hour token and a masked, deselectable list of scammer-role indicators.
  Reports require version-2 consent; identifiers are stored as peppered,
  key-versioned HMAC digests and template signatures are computed after
  redacting names, identifiers, amounts and dates. Indicator thresholds are 3+
  (+25) and 10+ (+40); template similarity >=0.8 adds +25. Correlated evidence
  is the highest indicator bucket plus template evidence, capped at +40 total;
  several identifiers do not stack. Community evidence alone cannot produce
  high risk: if it alone crosses 60, the score is capped at manual review with
  an explicit factor. Details disclose buckets only. Withdrawals delete a
  report's contributions. Reports are not
  independently verified and do not count as external verification. Disputed
  indicators keep scoring during review; only a same-domain email-verified
  domain dispute is temporarily suppressed. Inactive indicators expire after
  24 months. Digests/signatures are pseudonymised, not anonymous; legal review
  under the DPDP Act, 2023 and its Rules is required, including third-party
  sender data. Demo rows count only in `DEMO_MODE=1`.
- The model is `rule_based_v2`; it is a fixed rule table, not a trained ML model.
  GSTIN checks are structural. CIN lookup uses a local company-master SQLite copy;
  it does not contact a live service. An opted-in synthetic CIN fixture is
  available only in demo mode and is labelled in output. A synthetic company-master
  snapshot is also demo-only; its results are traceable via `registry_source`.

## OCR and rate limiting

- **OCR was verified in CI** by successful run `43403402979` on 2026-11-13 UTC (commit `51c6c2357ddf93566249e2287913d36a9b674263`). The log shows Tesseract and Poppler installed and the suite finished `143 passed` with no skipped tests or pytest warnings. This includes degraded-image robustness cases for the three demo PDFs across clean, 3° rotation, blur, and JPEG quality 30 variants. No band flips occurred; therefore there is no flip-causing extracted text to report. Passing cases do not print their OCR text. This verifies the CI environment, not the previously blocked local Windows Tesseract install.
- `RATE_LIMIT` controls requests per IP. The default is `10/minute`; with
  `DEMO_MODE=1` and `RATE_LIMIT` unset, the default is `100/minute`.

## Public scam-trends page

- **The page is public and aggregate-only.** It is open to anyone who can reach the
  site; there is no login, no per-college or per-user view, and one internal
  aggregate record ("Public") is created automatically.
- **Every check is counted anonymously.** Each successful
  `/analyze` call records exactly one aggregate row: UTC ISO week, risk band and
  rule-based scam category. The row holds no offer text, identifiers, file name,
  company name or IP address and is not linked to the analysis, a report or a
  person, so a report withdrawal does not remove it. Rows are deleted 24 months
  after their week. Purpose: anonymous trend counts; every
  count below five is shown as `<5`. A consented report adds no second row.
  Checks are not deduplicated by person, so counts
  are checks, not verified unique people. The senders table comes from consented
  community reports.
- With `DEMO_MODE=1`, `run_demo.bat` seeds 45 simulated reports (senders table)
  and 484 simulated checks (the same three fields) so the 12-week chart and
  category summary are populated; checks made in demo mode are also demo-flagged.
  Demo rows count only in demo mode. Two chart cells are deliberately below five.
- `GET /trends/dashboard` returns week-by-band and week-by-category
  counts for 12 ISO weeks and replaces cells below five with `"<5"`, a
  `category_summary` (per category: 12-week total, last 4 weeks, previous 8
  weeks, trend word by a ±25% weekly-rate rule; `<5` applied to each count; no
  trend word when the total is below five), `GET /trends/weekly.csv`
  with the full weekly data under the same rule, plus
  `top_senders`: masked indicators reported in 3+ consented (consent v4)
  reports, with type, count, first/last week, most common category and dispute
  status. `GET /trends/senders.csv` exports that list. Only masked
  display forms are stored for consented reports (never raw emails, phones, UPI
  IDs or account numbers); a non-free-mail sender domain is shown in full.
  Consent v4 tells people the public scam-trends page shows these masked details. Both
  endpoints are limited to 30 requests/minute. Categories derive from payment-demand, domain,
  sender-authentication and scheme-text rules; the README documents their
  priority and mapping.

## Database and CI

- **Postgres was verified in CI** by successful run `43403402979` on 2026-11-13 UTC (commit `51c6c2357ddf93566249e2287913d36a9b674263`). The job initialized a `postgres:15` service; Alembic logged `PostgresqlImpl`, applied revisions 001 through 004, and `alembic check` reported `No new upgrade operations detected.` The test step used the configured PostgreSQL `DATABASE_URL` and completed with `143 passed` and no pytest warnings.
