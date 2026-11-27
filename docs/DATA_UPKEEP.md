# Data upkeep

The checker uses two local, dated data sources. Nothing here runs while a check is being scored; scoring never
makes a network call for this data. Run `python -m scripts.upkeep_report` once a month: it prints each source's age
and exits 1 if one is stale (company snapshot older than 90 days, advisories older than 180 days) or undated.
The public "How it works" page shows the same ages.

## Company register snapshot

What it is: a local SQLite copy of company names, CINs, status and registration date. It is a periodic snapshot, not a
live registry, and the app must never describe it as official or live.

1. Get a snapshot you are allowed to use. Two routes exist in this repo:
   - Your own CSV (columns CIN, name, status, registration date): `python -m scripts.load_mca_master <file.csv> --db data/mca_master.sqlite3`.
   - The data.gov.in "RoC-wise Company Master Data" resource, with a personal key from your data.gov.in account in
     `DATA_GOV_IN_API_KEY`: `python -m scripts.sync_ogd_master --max-pages 5` first as a small trial, then without the
     limit. It pages politely and resumes with `--start-offset`. It is published under the Government Open Data
     License - India; read the licence and the portal's current terms before relying on it.
2. If the portal host, page size or field names have changed, the run fails rather than loading bad data. Set
   `DATA_GOV_IN_BASE_URL` (https only) if the host moved, and check the response by hand before changing the script.
   Whether the current API behaves as the script assumes has to be confirmed by running it (see `docs/LIVE_CHECKS.md`).
3. Run `python -m scripts.upkeep_report` and confirm the registry line says "current".
4. Do not commit the snapshot (it is large and may change); keep it on the host only.

## Employer fraud advisories

What it is: `app/data/brand_advisories.json`, statements an employer published on its own recruitment-fraud page,
with the page URL and the date it was read.

1. Open each `source_url` yourself. If the page moved or the wording changed, update `statement` to what the page says now
   (keep it short and factual) and set `retrieved` to today's date. Remove an entry whose page is gone.
2. To add an employer: open its own page, read its terms, then add the entry by hand. The helper
   `scripts/advisory_scraper.py fetch` can draft candidates from the allowlist in `scripts/advisory_sources.json`, but
   nothing it produces counts until a person approves it and runs `promote`. It obeys robots.txt and fails closed.
3. Known gap: Wipro and Cognizant have no entry because their pages have not been read and recorded yet. Do not add
   them from memory; each needs a page read by a person and dated.
4. Run `python -m scripts.upkeep_report`.

## Not part of upkeep (by design)

- No scheduled crawling and no LLM in the loop: every change to what the checker says about a company is a
  person reading a source and recording the date.
- Scam wording rules are not "updated" from scraped text; new patterns need hand-derived tests (see AGENTS.md).
