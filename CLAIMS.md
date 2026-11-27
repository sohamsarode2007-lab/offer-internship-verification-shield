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

## Company-master lookup

- No company-master data is included in this repository. Two optional sources can
  answer a CIN lookup, and each response carries the non-displayed field
  `registry_source`: `mca_csv` (a CSV the operator loaded locally with
  `scripts/load_mca_master.py`) or `ogd` (one lookup by CIN against the
  data.gov.in "RoC-wise Company Master Data" resource, made only when the operator
  sets `DATA_GOV_IN_API_KEY`). That resource is a periodically
  refreshed snapshot published under the Government Open Data License - India
  (attribution: Ministry of Corporate Affairs, data.gov.in), not a live registry;
  a company may have changed status since. If the API times out, is blocked or
  returns an unexpected payload the lookup reports "registry not checked", never
  "not found". A CIN absent from the snapshot is `insufficient_information`, not
  evidence against the company. Only CIN, name, status and registration date are
  read; addresses, capital and industry fields are discarded. The registry
  industry-classification column is not used because a sample row for a large
  IT-services company carried an unrelated manufacturing classification.
- Registry results read
  `Company registry match: <name>; Active; incorporated <date>.` for an active,
  name-matched company; failures lead with the problem: `Company is <status> in
  company registry records: <name>; incorporated <date>.` or `CIN belongs to a
  different company in company registry records: ...`.
- Company-name comparison expands legal suffixes (`Pvt.`/`Ltd.` to `Private`/
  `Limited`) before matching, and registry statuses meaning not operating
  (strike off, dissolved, liquidation, amalgamated) fail the check; `Dormant` does not.

## Disposable mailbox detection

- A contact or sender address on a known throwaway-mail service (for example
  mailinator.com or yopmail.com, or a subdomain of one) fails the domain check
  before any DNS lookup. It reuses the existing +30 "contact domain failed" weight;
  no new weight is added. The list in `app/utils/email_domains.py` is short and
  curated, not exhaustive: a throwaway service missing from it is not detected, and
  absence from the list says nothing about a domain. Free personal mailboxes such
  as Gmail keep their separate, existing finding. The rule is offline and does not
  verify who controls the address.

## Employer-published recruitment domains

- `app/data/brand_advisories.json` records what an employer's own fraud page says about
  where it recruits from, with the source URL and the date it was read. Currently three
  entries: TCS (`@tcs.com`), Infosys (`@infosys.com`) and HCLTech (`@hcl.com` or `@hcltech.com`, plus
  preferred recruitment partners, which its page also states). When an
  offer names one of them but the sender's domain is not that employer's listed domain or a subdomain, the domain check
  fails with wording attributed to that page ("Per TCS recruitment fraud alert ... TCS
  recruits only from ..."). It reuses the existing +30 domain weight; no new weight.
  The page was read through a summarising fetch tool, so the statement is paraphrased and
  the entry should be re-read against the page before it is shown in a demo as a quotation.
  Employers without an entry are not checked, and a staffing firm legitimately recruiting
  on an employer's behalf from its own domain would also be flagged: the result says the
  domain is not the employer's published one, not that the sender is a scammer.
- `scripts/advisory_scraper.py` can re-read allowlisted employer pages and propose entries, but it only
  writes candidates for a person to review; nothing it reads changes a result until a person approves
  and promotes the entry. It obeys robots.txt and has only been tested against mocked pages.

## PAN, Udyam and payments-bank structure checks

- A labelled `PAN:` value must match the PAN format, have holder type `C` when the claimed
  name says Pvt/Ltd, and equal the PAN embedded in a quoted GSTIN. A `UDYAM-XX-00-0000000`
  number must match that format. Failures reuse the existing +25 "registration number failed
  structural checks" weight; a structurally valid PAN or Udyam number without a registry record
  reuses the existing +10 "valid but not verified" weight. No new weights.
- These are format checks only. A valid PAN or Udyam number is not verified: this project has no
  PAN or Udyam registry source (the data.gov.in Udyam list has no Udyam-number column and is not
  used), and Udyam numbers are self-declared. The result says so.
- If a payment demand's text includes an IFSC whose bank code belongs to a payments bank
  (Airtel, Paytm, Fino, India Post), the payment details add an informational sentence. It adds
  no points (a payment demand already forces high risk) and never repeats the IFSC. The code list
  is short and from general knowledge of RBI bank codes, not an RBI download.

## Internet Archive first-seen note

- With `INFRA_AGE_LOOKUPS=1` (off by default) and only when WHOIS gave no usable domain age, the
  domain check adds one informational sentence with the month of the earliest successful capture in
  the Internet Archive's public CDX index. It never changes the status or the score: an archived copy
  does not show who sent an offer, and a missing copy proves nothing. Lookup failures add nothing.
  The endpoint was written from its public documentation and has not been exercised against the live
  service from the build environment (network access was blocked); tests use a mocked response.

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
  active, name-matched CIN from the locally loaded MCA SQLite master data whose
  registered company name also matches the contact domain (`app/services/identity_tie.py`),
  because a company number can be copied onto any offer. Email authentication results in
  an uploaded `.eml` are shown but never counted as a signal or as a score reduction:
  every header in an uploaded file is written by whoever made the file. A failed result
  still counts against the sender, because forging a failure only hurts the forger. Structural domain/GSTIN checks
  alone are capped at manual review.
- `scripts/load_mca_master.py` imports a company-master CSV into local SQLite and
  records its source (`MCA_CSV`). Rows marked
  `Synthetic=true` are refused so test-only rows cannot enter a runtime registry
  database. This workspace does not include official MCA data (future
  scope, eKYC required); lookup behaviour is tested with temporary database rows.
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
  Reports require version-4 consent; identifiers are stored as peppered,
  key-versioned HMAC digests and template signatures are computed after
  redacting names, identifiers, amounts and dates. Indicator thresholds are 3+
  (+25) and 10+ (+40); template similarity >=0.8 adds +25. Correlated evidence
  is the highest indicator bucket plus template evidence, capped at +40 total;
  several identifiers do not stack. Community evidence alone cannot produce
  high risk: if it alone crosses 60, the score is capped at manual review with
  an explicit factor. Details disclose buckets only (“3+ separate reports”, never “people”; reports are not verified unique people). Reports for one indicator count, and appear on the public trends page, only if they were made on at least two different days. Withdrawals delete a
  report's contributions. Reports are not
  independently verified and do not count as external verification. Disputed
  indicators keep scoring during review; only a same-domain email-verified
  domain dispute is temporarily suppressed. Unresolved disputes lapse after 90 days. Inactive indicators expire after
  24 months. Digests/signatures are pseudonymised, not anonymous; legal review
  under the DPDP Act, 2023 and its Rules is required, including third-party
  sender data. Rows flagged `is_demo` from older builds never count.
- Employer confirmation message: a fixed-wording message the person can copy and send to contact details they find
  themselves. The only offer-derived value is the company name (already shown on the result, never stored). It never
  claims a verified contact, is not sent by the tool, and is not offered when a payment demand was found.
- Deployment hardening: with `ENVIRONMENT=production` the app refuses to start on an unsafe configuration (short
  or missing pepper, localhost/`*` origins, SQLite, rate limiting off); responses carry nosniff, frame-deny,
  no-referrer and a Content-Security-Policy; access logs are off by default; stored analysis results are deleted
  after 365 days. The Docker build and the CSP were not exercised in a real browser or container from the
  build environment.
- The model is `rule_based_v2`; it is a fixed rule table, not a trained ML model.
  GSTIN checks are structural. CIN lookup uses a local company-master SQLite copy
  or an opted-in data.gov.in CIN lookup (`DATA_GOV_IN_API_KEY`).

## OCR and rate limiting

- **OCR was verified in CI** by successful run `43403402979` on 2026-11-13 UTC (commit `51c6c2357ddf93566249e2287913d36a9b674263`). The log shows Tesseract and Poppler installed and the suite finished `143 passed` with no skipped tests or pytest warnings. This includes degraded-image robustness cases for the three demo PDFs across clean, 3° rotation, blur, and JPEG quality 30 variants. No band flips occurred; therefore there is no flip-causing extracted text to report. Passing cases do not print their OCR text. This verifies the CI environment, not the previously blocked local Windows Tesseract install.
- `RATE_LIMIT` controls requests per IP. The default is `10/minute`.

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

## Scam-chat wording

- `app/services/scam_text.py` matches fixed phrase patterns typical of WhatsApp/Telegram job scams
  (paid tasks for liking or rating, pay-to-withdraw, recruiter reachable only by chat, no-interview
  and easy-money claims) and advance-fee wording (fake cheque with a balance to send back, package
  re-shipping, buying gift cards or sharing their codes, sending crypto to a wallet, sharing an OTP,
  CVV or PIN, sending an "overpayment" back). The advance-fee families are the strong tier. It is wording only: it does not know whether a person or group is a scammer.
- Weights: strong tier +30 and it blocks "likely legitimate"; moderate tier +15; both tiers +40 in total.
  A negation earlier in the sentence ("we never ask you to join Telegram") cancels a match.
- No match is reported as "not applicable", never as a pass: absence of these phrases does not show
  an offer is genuine. The result names the rule families and never repeats the offer text.
- Patterns were written from publicly described scam wording, not trained on data, and will miss
  paraphrases and other languages. Genuine recruiters occasionally use WhatsApp, which is why that
  rule is the moderate tier.

## UPI payment links and QR codes

- A `upi://pay` or `upi://mandate` link in the text, or in a QR code inside an uploaded image or PDF (decoded
  offline with OpenCV), counts as a payment demand and so forces "high risk" like any other payment demand.
- Only the payee address and amount are read. The payee name and note are ignored and not shown or stored;
  the redaction step removes the whole link before any text is used for similarity matching.
- Limits: QR codes are read from image uploads and from the first 3 pages of a PDF (rendered in memory at 150 dpi, best
  effort, never written to disk; QR images embedded in oversized pages are skipped), only when OpenCV can
  detect them (small, blurred or angled codes may be missed), and QR codes holding web addresses are ignored.

## Safety steps

- When a payment demand, an advance-fee wording family (fake cheque, reshipping, OTP, gift card, crypto), a flagged
  link or a high-risk result is found, the result lists matched what-to-do-now steps. They are fixed advice text:
  nothing is built from the offer, nothing is stored, and no action is taken for the person.
- The contacts are the National Cyber Crime Helpline 1930 and the National Cyber Crime Reporting Portal
  (cybercrime.gov.in), confirmed against Kerala Police and Ministry of Home Affairs pages. The steps are general
  advice, not legal advice, and a report does not guarantee any money is recovered.
- If money may have been transferred, the advice also says to contact the bank or payment app immediately and ask
  what hold or reversal options are available. The application does not contact the bank, file a complaint, or take
  any action for the person. A payment warning says a legitimate employer should not require a fee, deposit, kit
  charge, or security amount as a condition of getting the job or internship; it is guidance, not proof about a
  particular employer.

## Link lookups (Web Risk, redirects, certificates)

- Off by default. Runs only when the operator sets `LINK_LOOKUPS=1` and the person ticks the consent box for that
  check. For up to 3 links it asks Google Web Risk's Lookup API (needs `WEB_RISK_API_KEY`) and follows redirects from
  this server (HEAD only) to read the landing site's certificate.
- Possible findings, all informational with no score effect: "threat-listed" by Web Risk, a redirect to a different
  site, 3+ redirects, a certificate that does not verify, or one issued under 14 days ago. Everything else is
  "unknown": a link that is not flagged is never described as safe, and an unreachable service adds nothing.
- Outbound safety: the server resolves a link's name once, refuses the link unless every address is public, and
  connects to that same checked address (so a name that changes its answer cannot redirect the request to an internal
  address). Redirects are followed one hop at a time with each hop checked the same way. All link checks for one
  analysis share an 8 second deadline and run in parallel. Each connection gets 5 link-checked analyses per hour
  (`LINK_CHECKS_PER_HOUR`); beyond that the result says link checks were skipped. The same pinned client is used for
  the optional careers-page lookup. `/sources` shows each lookup only as available or paused, not exact usage.
- Only a minimised address is sent (no query, fragment or login part); nothing is stored or logged. See
  docs/PRIVACY_DESIGN.md. Tests use mocked responses: the Web Risk request shape follows Google's published
  Lookup API documentation but was not run against the live service from the build environment.
- VirusTotal is not used: its free API is capped at 500 requests a day and barred from commercial products.

## Upload limits

- A request body over 52 MB on `/analyze` (256 KB elsewhere) is refused with 413 as soon as the size is known,
  from `Content-Length` or by counting streamed bytes, before the upload is parsed. A reverse proxy limit should
  sit in front of this as well; this is the second line, not a replacement.
- Per file: 10 MB, up to 5 files, text extracted capped at 50,000 characters. Text-layer PDFs over 60 pages are
  refused; text collection stops at a character budget. Scanned PDFs: at most 10 pages, rendered and read one page
  at a time, 30 s per page render, 20 s per OCR call and 90 s for the whole document. A `.eml` may have at most 60
  parts and 400 headers, keeps at most 5 PDF/image attachments, and refuses an attachment over 10 MB (20 MB total).
- At most 4 analyses run at once per server process; a request that cannot get a slot within 3 s gets 503.
- The optional EasyOCR and PaddleOCR engines cannot be interrupted once started, so they are off unless the operator
  sets `HEAVY_OCR=1`; by default only Tesseract (hard 20 s limit per call) reads images. Do not enable them on a
  public deployment. A Tesseract timeout stops the job rather than falling through to another engine.

## Data sources panel and request budget

- The "How it works" page shows each source with the date it was last refreshed and its age: the local company
  registry snapshot (flagged out of date after 90 days; a snapshot marked synthetic is ignored and reported as date unknown) and the
  hand-read employer advisories (out of date after 180 days, measured from the oldest page read). A source with no
  date is shown as "date unknown", never as current. It also shows the rules version and how many optional online
  lookups are switched on. No secrets and no offer data are involved.
- Web Risk lookups have a daily budget (default 3,000 a day, `WEB_RISK_DAILY_BUDGET`) held in memory per server
  process. When it is spent, the lookup is skipped and shows as "unknown". The count resets each UTC day and on restart.
- The 90 and 180 day thresholds are our judgement, not a published schedule of the sources.

## Downloadable report

- "Download full report" builds a Markdown file in the browser from the result already on screen: outcome, score,
  reasons, checks, where each check comes from, safety steps, self-checks, next steps and the limits. Nothing is
  uploaded or stored, and the offer text and uploaded file names are never included (a test checks this). It names
  the company if the result did. It is an automated, rule-based review, not legal advice or a police finding.

## Careers-page note

- With `CAREERS_PAGE_LOOKUPS=1` (off by default) and a domain that passed the domain check, one informational
  sentence says the domain serves a page that reads like a careers page. It never changes the status or the
  score, and a missing page is never reported: anyone can publish a careers page on a domain they control, so
  it does not show who sent an offer. Fetches are https only, to public addresses only, with no redirects,
  a 64 KB cap and a 3 s timeout; page content is not stored or shown. Tests use mocked responses; the check
  has not been run against live sites from the build environment.

## Add evidence and check again

- The result page lists what could make the check stronger (original email, sender address, company
  registration details, payment screenshot), chosen only from which checks could not run. No hint is shown
  when a payment demand was found, because nothing can change that verdict.
- "Check again" re-sends the earlier text plus the new text from the browser's memory. The server keeps
  nothing between the two checks, so the offer text is still never stored. Only one file is checked at a time.

## data.gov.in bulk sync

- `scripts/sync_ogd_master.py` copies the public "RoC-wise Company Master Data" snapshot into a local database
  using your own API key. It keeps four fields only. The data is a periodic snapshot, not a live registry, and a
  company can change status after it was published.

## Plausibility notes (no score impact)

- `app/services/plausibility.py` adds notes to the "Why" list, with no score change, for: a stated pay far above
  normal for an internship or fresher role (Rs 1,00,000 a month or 30 LPA and above), a +91 number that cannot
  be an Indian mobile or a non-Indian country code, and a PDF last saved by a known online design or editing tool.
- Each has common innocent explanations, which is why none of them affects the result. A note never repeats the
  amount, number or any PDF metadata. The PDF check reads only the producer and creator fields against a fixed list.
- A check that the employer's careers page lists the role is not built: it needs live web access and is easy to
  get wrong.

- Live lookup tuning (`DATA_GOV_IN_BASE_URL`, `MCA_LIVE_LOOKUP_TIMEOUT`, `INFRA_AGE_TIMEOUT`) only changes where and how long
  the app waits; it never changes a score. Live lookups are throttled to about two per second per process.

- The scam-wording rules include a small set of Hinglish and Devanagari Hindi phrasings. They are narrow, have not been
  reviewed by a native speaker, and most Hindi/Hinglish scam wording will not match.

- **Udyam self-check.** When the offer quotes a well-formed Udyam number, the result shows it with a link to the government
  Udyam verification page so the person can check it themselves. The tool does not query that page (it needs a captcha),
  does not verify the number, adds no score, and never stores the number.


- **Evidence source line.** Each check in the result shows its source (offer text, email headers, DNS lookup, local company
  snapshot or community reports), whether it affects the score, forces high risk or has no effect, and a
  confidence. A check that could not tell (unknown or not applicable) shows "not enough to tell", never a pass. The
  record holds no offer text or identifiers.

- **Link patterns.** The "Why" list notes when a link in the offer uses a known URL shortener, an `xn--` (punycode)
  domain, a domain mixing look-alike alphabets, a raw IP address or an `@` trick. These are structural checks of the
  text only: no link is opened, no redirect is followed and no reputation service is asked. They add no score and never
  repeat the link.

- **PDF structure notes.** For an uploaded PDF, the "Why" list notes active content (scripts or auto-run actions),
  embedded files, a modification date well after creation, a future creation date, changes appended after the first
  save, and pages of mixed sizes. The file is only parsed, never run, and stays in memory; notes add no score and never
  repeat a metadata value. Genuine letters are sometimes edited, so these are hints, not proof.

- **Several files in one check.** Up to five files (PDF, image, `.txt`) can be sent together with pasted text; their text
  is joined and scored as one offer, and nothing is stored. An `.eml` must be sent on its own so its sender checks run.
  A note appears when two files contain almost the same wording; it adds no score.

- **Request for bank details or documents.** If the text asks the candidate to send bank details (+20) or identity
  documents such as Aadhaar, PAN, passport or original certificates (+10), the "Why" list says so. The two are not
  added together, and a request placed after joining or negated ("do not send ...") is ignored. It is a pattern match on
  wording, not proof of a scam: some genuine employers ask for these before the start date. It can never produce high
  risk on its own; only a payment demand does that. Nothing from the text is stored.

- **What it cannot catch (stated plainly).** A scam that copies a real company's registration number and uses a contact
  domain that is exactly that company's name, with a clean domain history, looks the same as a genuine offer to
  everything this tool can see, and can be rated "likely legitimate". The tool cannot tell who controls a domain. A
  "likely legitimate" result is therefore never proof: the result page is headed "No red flags found", says "Not proof"
  and tells people to confirm through the employer's own website. The evaluation fails on any other scam rated that way. This case is kept in the evaluation set (EC41) as a known miss and is not hidden or tuned away.

- **Request for a password, PIN or OTP.** If the text asks the candidate to share a password, PIN, OTP or card security code
  (+40), the "Why" list says no genuine employer needs these. Unlike bank details and documents, "after joining" wording
  never cancels this warning; only a negation ("never share your OTP") does. It is a wording match, not proof.
