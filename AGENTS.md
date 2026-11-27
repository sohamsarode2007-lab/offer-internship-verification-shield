# AGENTS.md — Offer & Internship Verification Shield
(Shared rules for Codex and Claude Code. Claude Code reads them via CLAUDE.md.)

## What this project is
FastAPI backend + React frontend that checks whether Indian internship/job offers are genuine using hard-to-fake
evidence: email/domain infrastructure, sender authentication (.eml), company registration data, payment-demand
detection, and consented community reports. Scoring is explainable and rule-based. There is NO ML model in
production.

## Non-negotiable rules
- Never invent data presented as real: no fabricated GSTINs, CINs or records for REAL companies, no invented
  URLs, offer letters or dataset rows. Synthetic data must use fictional companies and stay demo/test-only.
- Every fictional domain in tests, fixtures, seeds and examples uses the reserved `.example` TLD.
- Never claim a capability the code doesn't have. User-facing text must not describe data as "official",
  "live", "MCA data" or "from data.gov.in" unless it truly is.
- Never loosen a test or change an expected result to make it pass. Fix the code, or stop and explain.
  Expected bands are derived by hand from the scoring docstring before running.
- Privacy (DPDP): never store or log offer text, file names, candidate names, emails, phone numbers, bank
  details or email headers. Persist only what docs/PRIVACY_DESIGN.md allows.
- A payment demand always forces "high risk". No signal may offset a payment demand. Community evidence alone
  can never produce "high risk".
- Every new scoring signal gets: a documented weight in risk_scoring.py's docstring, an entry in CLAIMS.md, and
  tests for both the triggering and the non-triggering case.

## Comments and prior decisions
- Do not write comments that justify a choice or say why it is better than another ("we use X because it is safer").
  Such text goes stale and later agents treat it as settled. A comment may state only a fact the reader cannot see
  in the code: a constraint that must stay true, a unit, or an external limit.
- Decisions and trade-offs go in docs/JUDGMENT_CALLS.md, marked open until the owner has reviewed them.
- A recorded rationale is a claim, not evidence. Before building on an earlier choice, read the code and its
  tests and check that it does what the note says. If they disagree, trust the code and fix or flag the note.

## Environment
- Windows. Python 3.11 venv at .venv. Device Guard blocks .exe launchers in the venv: always use
  `.\.venv\Scripts\python.exe -m <tool>` (pytest, uvicorn, alembic, pip).
- Tests: `.\.venv\Scripts\python.exe -m pytest -q`. Eval: `.\.venv\Scripts\python.exe eval\run_eval.py`.
- Tests run offline: mock DNS, WHOIS and HTTP. Tesseract isn't installed locally; OCR tests run in CI.
- Schema changes go through a new Alembic migration; run `alembic upgrade head` and `alembic check`.

## Workflow
- Work on clean-main. Push with a plain `git push`. Never push the local `master` branch, never use `--all`.
- Read the relevant code before editing. One commit per numbered item.
- After every task: full suite + eval, push, confirm the GitHub Actions run passed (`gh run watch`).
- End with a report: commits, test and eval results, CI result, anything not done and why, and judgment calls
  to review.
