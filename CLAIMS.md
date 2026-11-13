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

## Payment detection and scoring

- Payment detection uses phrase rules and UPI payment context. A nearby UPI VPA
  (within 200 characters of an already-detected, non-negated demand phrase) is
  reported as `UPI payment instruction: <vpa>` in the payment check details.
- Stipend, salary, and reimbursement context remains excluded from standalone UPI
  payment-demand detection. Negated fee phrases are not treated as demands.
- The payment-demand signal is worth 65 points, with urgency near the demand worth
  20 additional points. A payment demand forces a high-risk score of at least 61.
  See the scoring table in `app/services/risk_scoring.py`.
- **Known limitation:** urgency without a detected payment demand adds no score.
  Synthetic case EC08 is labelled `scam` but scores `likely legitimate`: its demo
  domain pass offsets the +10 valid-but-unverified GSTIN, and its deadline alone
  is not weighted. This is reported as a dangerous miss even though the
  rule-derived expected-band check passes. Adding +31 for expiry/deadline language
  would move EC08 into manual review, but would change its existing regression
  result and could send legitimate offer acceptance deadlines to manual review;
  that rule has not been implemented.
- The model is `rule_based_v2`; it is a fixed rule table, not a trained ML model.
  GSTIN/CIN checks are structural and do not query a live registry.

## OCR and rate limiting

- **OCR was verified in CI** by successful run `43378004125` on 2026-11-13 UTC
  (commit `ae741a05136f1c0496629df7840493fdb30ca9e7`). The log shows the OCR
  binary-install step completed and the test suite finished `71 passed` with no
  skipped tests. This includes the degraded-image robustness cases for the three
  demo PDFs across clean, 3° rotation, blur, and JPEG quality 30 variants. No band
  flips occurred. Passing cases do not print their extracted OCR text, so the logs
  contain no extracted text to report; there is no flip-causing text. This verifies
  the CI environment, not the previously blocked local Windows Tesseract install.
- `RATE_LIMIT` controls requests per IP. The default is `10/minute`; with
  `DEMO_MODE=1` and `RATE_LIMIT` unset, the default is `100/minute`.

## Database and CI

- **Postgres was verified in CI** by successful run `43378004125` on 2026-11-13
  UTC (commit `ae741a05136f1c0496629df7840493fdb30ca9e7`). The job initialized a
  `postgres:15` service; Alembic logged `PostgresqlImpl`, applied revisions 001
  and 002, and `alembic check` reported `No new upgrade operations detected.` The
  test step used the configured PostgreSQL `DATABASE_URL` and completed with
  `71 passed, 3 warnings`.
