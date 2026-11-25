# Judgment calls to review

Decisions made while building the `india-upgrades` work that you may want to change. Each entry says
what was decided, why, the risk, and how to reverse it. New entries are added at the bottom as the
work continues; nothing here is final until you have reviewed it.

Status: **open** = not reviewed yet.

| # | Call | Status |
|---|------|--------|
| 1 | Udyam registry dataset skipped | open |
| 2 | data.gov.in live CIN lookup is opt-in, local snapshot first, fail-closed | open |
| 3 | Company-name match expands `Pvt.`/`Ltd.` before comparing | open |
| 4 | Registry status "inactive" matched by word stems; `Dormant` is not a failure | open |
| 5 | Registry industry-classification column is not used | open |
| 6 | Consent bumped to version 4; versions 1-3 rejected | open |
| 7 | Public trends page: one aggregate record, counts are checks | open |
| 8 | "students" replaced with "people" / "job seekers" in code, tests and docs | open |
| 9 | Disposable-mailbox list is short and curated | open |
| 10 | Employer advisories: TCS, Infosys, HCLTech; staffing-firm false positive accepted | open |
| 11 | PAN and Udyam are format checks only; existing weights reused | open |
| 12 | Payments-bank IFSC codes come from general knowledge, add no points | open |
| 13 | Internet Archive first-seen note is opt-in and untested against the live service | open |
| 14 | Portal link claims only "report the sender" | open |
| 15 | CI lint gate is pyflakes-only; audit covers `requirements.txt` only | open |
| 16 | Deployment (Render/Vercel) work deliberately left alone | open |
| 17 | Advisory scraper is semi-automated: a person approves every entry | open |
| 18 | Scam-chat wording rules: weights, tiers and the new trend category | open |
| 19 | A UPI link/QR in an offer always counts as a payment demand | open |
| 20 | Re-check is stateless (browser re-sends text); hint cards, ledger left as a table | open |
| 21 | Bulk data.gov.in sync; Infosys and HCLTech advisories added, Wipro and Cognizant not | open |
| 22 | Pay/phone/PDF-metadata notes are informational only; careers-page check not built | open |
| 23 | Eval set grown to 41; EC41 is a deliberate dangerous miss | open |

## 1. Udyam registry dataset skipped
- **Decided:** do not use the data.gov.in "List of MSME Registered Units under UDYAM" dataset.
- **Why:** it has no Udyam-number column and no enterprise-type column, so the only possible match is a
  company-name match inside a state, which collides on common names and cannot confirm a Udyam number.
- **Risk:** a letter that gives only a Udyam number gets format checks, not a registry check.
- **Reverse:** add a loader for the name/state/pincode columns and show a match as informational only.

## 2. data.gov.in live CIN lookup
- **Decided:** one lookup by CIN, only when `DATA_GOV_IN_API_KEY` is set, DEMO_MODE is off and the CIN is
  not in the local snapshot. 2.5 s timeout. The shared public sample key is never used. Any failure means
  "registry not checked", never "not found". Only CIN, name, status and registration date are read.
- **Why:** the endpoint answered a `filters[CIN]` query with exactly one row in your test; a failure must
  not look like evidence against a company.
- **Risk:** data.gov.in may block cloud IPs (not tested from a server). The data is a snapshot (the
  dataset was last updated 2026-10-13 when you tested), so a status may be out of date.
- **Reverse:** unset the key to disable it.

## 3. Company-name match expands legal suffixes
- **Decided:** `Pvt.`, `Pvt`, `Ltd.`, `Lmtd` become `Private`, `Limited` before names are compared.
- **Why:** registry names say `PRIVATE LIMITED`, letters say `Pvt. Ltd.`; the old comparison scored 85.7
  (needs 90) and called genuine companies "a different company", which adds risk points.
- **Risk:** low. Only legal-form words are expanded, so different names still fail (tested).

## 4. Inactive registry statuses
- **Decided:** a status containing `strik`, `struck`, `dissol`, `liquidat` or `amalgamat` fails the check;
  `Dormant` does not.
- **Why:** the real data uses wording like `Strike Off`, which the old exact list did not match, so a
  struck-off company passed. The wording list is partly from secondary sources, not the full data.
- **Risk:** a status I have not seen could be missed or over-matched. **Reverse:** edit `_INACTIVE_STEMS`.

## 5. Industry classification not used
- **Decided:** the registry's industry column is discarded.
- **Why:** your sample row for a large IT-services company carried a manufacturing (paper) classification.

## 6. Consent version 4
- **Decided:** the consent text changed (it named one college), so it is version 4. Versions 1-3 are
  rejected. Reports saved under version 3 no longer appear in the senders table.
- **Why:** changing consent wording without a new version would misrepresent what people agreed to.
- **Risk:** existing seeded demo data must be re-seeded. **Reverse:** not recommended.
- **Needs a legal read:** the text and the DPDP position were not reviewed by a lawyer.

## 7. Public trends page
- **Decided:** `/trends/*`, one internal aggregate record named "Public", no login, counts described as
  checks (not unique people), `<5` suppression kept.
- **Risk:** an open page with no login; it holds only aggregate counts and masked senders seen in 3+ reports.

## 8. Wording: "people" / "job seekers"
- **Decided:** replaced "students" in user-visible text, code, tests and docs to match a general audience.
- **Risk:** some prose in older docs may still read oddly; tell me where.

## 9. Disposable-mailbox list
- **Decided:** about 33 well-known throwaway-mail domains plus subdomains; fails the domain check before DNS.
  Reuses the existing +30 weight.
- **Risk:** it is not exhaustive and is not from a maintained feed. **Reverse:** edit `DISPOSABLE_EMAIL_DOMAINS`.

## 10. Employer advisories
- **Decided:** only TCS is listed, because it is the only employer page I actually opened. A letter naming
  TCS from another domain fails the domain check with wording attributed to TCS's page.
- **Risk:** a staffing firm legitimately recruiting for TCS would be flagged (the wording says "not TCS's
  published domain", not "scammer"). The page was read through a summarising tool, so re-read it before
  quoting it in a demo. **Reverse:** remove the entry from `app/data/brand_advisories.json`.

## 11. PAN and Udyam format checks
- **Decided:** labelled `PAN:` values and `UDYAM-XX-00-0000000` numbers are format-checked; a company PAN
  must have holder type `C` and match the PAN inside a quoted GSTIN. Failures reuse +25, valid-but-unverified
  reuses +10. The Udyam state code is not checked (I do not have a verified list).
- **Risk:** a legitimate letter quoting a wrong PAN would be flagged. Result text says format only.

## 12. Payments-bank IFSC note
- **Decided:** bank codes AIRP, PYTM, FINO, IPOS add an informational sentence to a payment demand. No points.
- **Why:** a payment demand already forces high risk.
- **Risk:** the code list is from general knowledge, not an RBI download. **Please verify against RBI.**

## 13. Internet Archive first-seen note
- **Decided:** opt-in (`INFRA_AGE_LOOKUPS=1`), only when WHOIS gave no domain age, informational only.
- **Risk:** written from public documentation; never run against the live service from the build environment.

## 14. Portal link
- **Decided:** the result card links to the National Cyber Crime Reporting Portal for high-risk and
  insufficient-evidence results and claims only that the sender can be reported there.
- **Why:** I could not verify a "check suspect" lookup feature, so the UI does not promise one.

## 15. CI gates
- **Decided:** ruff runs pyflakes and syntax rules only; `pip-audit --strict` covers `requirements.txt`
  (not `requirements-dev.txt` or the frontend); the eval runs in CI and fails on a changed band.
- **Why:** a wider ruleset would touch many files; widen it deliberately.

## 16. Deployment left alone
- **Decided:** no Render/Vercel work, per your instruction. Known leftovers: uvicorn is started without
  `--proxy-headers` in the Dockerfile and rate limits are per-process, so a hosted deployment may rate-limit
  all users together.

## 17. Advisory scraper: automated reading, human approval
- **Decided:** `scripts/advisory_scraper.py fetch` reads only pages listed in `scripts/advisory_sources.json`,
  writes *candidates* (`approved: false`, empty `statement`), and `promote` merges only approved, validated
  entries into `app/data/brand_advisories.json`. Nothing it fetches changes scoring by itself.
- **Why:** an employer page that is rewritten, hijacked or mis-parsed must never silently change what the
  app tells job seekers, and a wrong "official domain" would wrongly flag genuine offers. Aliases (how a letter
  names the employer) are chosen by a person because guessing them risks matching the wrong company.
- **What it does for you:** re-reads the page, lists the own-domain e-mail addresses it finds, shows a diff
  against the stored entry (`changes_vs_current`) so you can spot a changed domain list, and suggests up to 3 short
  redacted sentences.
- **Safety rules built in:** https only, robots.txt obeyed (unreadable = skipped), contact-bearing User-Agent
  required, same-host redirects only, 1 MB / 10 s caps, 2 s between sources, phone numbers dropped and e-mail local
  parts removed at extraction.
- **Risks:** (a) whether a site's terms allow automated reading is a human check before adding it to the allowlist;
  (b) only short excerpts are kept, with the source URL, but copyright is your call; (c) the extractor is
  heuristic, so always read the page yourself before approving; (d) **never run against a live site from the build
  environment** (network blocked), so it is tested only with mocked pages.
- **Not built (on purpose):** crawling news sites or government portals, and any unattended scheduled run that
  would publish entries without review. Say if you want a scheduled "re-check and report changes" job instead.

## 18. Scam-chat wording rules
- **Decided:** new check `scam_text_patterns`. Strong tier (paid tasks, pay-to-withdraw) +30 and blocks the
  "likely legitimate" band; moderate tier (WhatsApp/Telegram-only recruiter, no-interview or easy-money wording)
  +15; both +40. It never forces "high risk" by itself; a letter with no identifiers and strong wording reaches
  70 through the existing "no registration number / no domain" points.
- **Why these weights:** the strong patterns describe the scam arrangement itself, while the moderate ones also
  appear in some genuine recruiter messages, so they are weaker.
- **Changed on purpose:** new trend category `task_or_chat_scam` (so the pinned category-set test changed), and the
  demo seed's synthetic weekly counts were rebalanced so the demo chart still shows most category cells.
  Real data is unaffected.
- **Risks:** English-only; phrase lists come from public descriptions of these scams, not from a dataset, so they
  will miss paraphrases; a genuine employer that recruits only over WhatsApp would get +15.
- **Reverse:** change `W_SCAM_*` in `risk_scoring.py`, or move a family between tiers in `scam_text.py`.

## 19. UPI link / QR code = payment demand
- **Decided:** any `upi://pay` or `upi://mandate` payload (typed, pasted, or decoded from a QR in an uploaded
  image) is a payment demand, so the result is "high risk". The payee address becomes a community indicator even
  when its handle is not on our known-handle list, because a upi:// payload is a payment destination by definition.
- **Why:** a genuine employer's offer has no reason to carry a payment QR for the candidate to pay.
- **Risk:** a genuine letter that includes a payment QR (for example an event fee a real college asks for)
  would be flagged high risk. That matches the project rule that a payment demand is never offset.
- **Not done:** QR inside PDFs, QR containing web links, and scanned phone photos at an angle; OpenCV's detector
  is decent, not perfect. No new dependency: OpenCV was already required.

## 20. Add-evidence re-check, stateless
- **Decided:** the browser keeps the first submission in memory and re-sends it with the extra text/file, so the
  server still stores nothing and no "session" exists. Hints come from which checks could not run, not from text.
- **Why:** a server-side draft of the offer would break the "we never store your offer" promise.
- **Trade-offs:** closing the tab loses the draft; one file per check (a new file replaces the old one); the
  evidence table was not turned into cards, only the hint cards are new.
- **Reverse / extend:** accepting several files means changing `/analyze` to take a list of files.

## 21. Bulk sync script and more employer advisories
- **Sync:** `scripts/sync_ogd_master.py` pages through the data.gov.in company master (0.5 s minimum between
  requests, page size capped at 1000, 3 tries per page, resumable with `--start-offset`) and keeps only CIN, name,
  status and registration date. Run it with `--max-pages 5` first. **Not run against the real API from here**
  (network blocked), and I have not confirmed the API's real maximum page size or whether it caps offsets, so the
  1000 cap is my assumption. I did not add the extra environment variables from your pasted list yet.
- **Advisories added (pages opened and read on 2026-11-17):** Infosys and HCLTech. Aliases are deliberately narrow
  ("Infosys Limited", not "Infosys", because Infosys BPM uses a different domain; "HCL Technologies", not "HCL",
  because HCL Infosystems and HCL Healthcare are different companies). HCLTech's page says offers may also come from
  its preferred recruitment partners, so the stored statement says so and a partner's domain would still be flagged
  as "not HCLTech's own", which is the same staffing-firm false positive as TCS.
- **Not added:** Wipro (its page refuses automated reading, so I could not read it) and Cognizant (the page hides
  its email addresses, so no domain is stated). Adding either from memory would break the no-invention rule.
- **Scraper allowlist unchanged:** I have not checked these sites' terms for automated reading, so they are not
  on `advisory_sources.json`. Entries were added by hand from the pages I read.

## 22. Plausibility notes (informational) and what was left out
- **Decided:** unusual pay, odd phone numbers and PDFs saved by online editors appear as notes with no score impact,
  and so have no weight in the scoring docstring.
- **Why:** each has many innocent causes (well-paid graduate schemes, numbers typed wrongly, people exporting from
  Canva), so counting them would flag genuine offers. If you want them to score, say which and by how much.
- **Thresholds are my guesses:** Rs 1,00,000 a month and 30 LPA for fresher/intern wording; the editor list
  (Canva, iLovePDF, Smallpdf, Sejda, PDFescape, PDF24, Photoshop, PDFfiller) is short and from general knowledge.
- **Not built:** (a) careers-page consistency (needs live web access and per-site parsing); (b) phone-number
  reputation lookups (no free reliable source); (c) logo and signature image checks (no dependable offline method).

## 23. Eval set grown from 22 to 41 cases
- **Decided:** 19 new hand-derived cases (EC23-EC41): six realistic genuine offers that must stay legitimate, the new
  rules firing, and two known-gap cases. All matched my hand calculation on the first run.
- **EC41 is a deliberate "dangerous miss":** a scam copying a real company's CIN with a passing domain looks genuine.
  The eval now reports "1 dangerous miss(es)" instead of 0. I kept it because hiding the limit would be dishonest;
  say if you would rather keep it out of the CSV and list it only in the README.
- **Limits:** the cases are still written by the same person (me) who wrote the rules, so they test that the rules
  do what I intended, not that they match real-world offers. A real evaluation needs offers collected independently
  and frozen before tuning (see the held-out rule in `eval/README.md`).

24. **Env-variable review note, verified against the code (open).**
- **Confirmed and done:** `GSTIN_REGISTRY_API_KEY` and `WHOIS_API_KEY` were read by no code, so they were removed
  from `.env.example`. Added optional `DATA_GOV_IN_BASE_URL` (https only), `MCA_LIVE_LOOKUP_TIMEOUT` and
  `INFRA_AGE_TIMEOUT` (both clamped to 0.5-10 s), a 0.5 s outbound throttle on live lookups, and an absolute
  `MCA_DB_PATH` plus a read-only `./data` mount in docker-compose.
- **Not accepted:** the claim that api.data.gov.in "died in Sep 2026". A web search found nothing supporting it and a
  live call worked in November. The host is now overridable, so a real move costs one env change.
- **Not added:** `MCA_STATE_CODES`. No evidence the API supports state filters on this resource, so it would be a guess.

25. **Hinglish/Hindi wording rules (open, needs a native-speaker review).**
- **Source:** Codex's unpushed draft, tightened. Its "deposit ... withdraw/unlock" rule flagged ordinary bank-intern and
  onboarding sentences as the strong tier, and Hindi negation after the phrase ("select nahi karte") was ignored.
- **Decided:** "deposit"/"unlock" dropped from the Hindi rules (recharge/top-up/"paise jama" only); a Hindi negation word
  shortly after a match in the same sentence cancels it; the danda (।) ends a sentence; a few Devanagari patterns added.
- **Known limit:** coverage is narrow. Everything not in the tests still abstains. EC40 moved from known gap to
  "high risk"; EC42-EC45 added (two guard against false alarms).

26. **Udyam "check it yourself" instead of automated verification (open).**
- **Decided:** no captcha solving and no agent or crawler on udyamregistration.gov.in. The captcha exists to stop
  automated look-ups, so we hand the person the number and the official link (a fixed constant) with honest wording.
- **Also decided:** zero score effect, hidden when a payment demand was found, shown only for a strictly valid format,
  number returned in the response only (not stored or logged).
- **Revisit:** a paid verification API (Surepass, Attestr, Zoop) if the team accepts sending each number to a third party.

27. **UPI handle no longer appears in check text (open, audit finding A1).**
- **Why a test changed:** `test_govt_scheme_payment_details_include_upi` asserted the raw handle was in the stored
  check details. That contradicts docs/PRIVACY_DESIGN.md ("raw ... UPI IDs ... are never stored"), so the test was
  rewritten to assert the opposite (instruction named, handle absent). The scoring result is unchanged.
- **Added:** tests/test_no_raw_upi_persisted.py checks the response and every analysis table for the handle.


28. **Migrations 005 and 007 made non-destructive (open, audit findings A3).**
- **005:** old observations are copied to `institution_observations_legacy` before the live table is emptied (they do not
  fit the consented-report model, so they stay out of the dashboard). `alembic check` ignores `*_legacy` archive tables.
- **007:** rows are marked simulated only when linked to a report carrying the demo seeder's marker, not because
  `is_demo` is true. Older unlinked demo rows are ambiguous and stay unmarked (they still count only in DEMO_MODE).
- **Limit:** databases that already ran 005/007 are unchanged; this protects fresh and older databases. Editing an
  applied migration is normally avoided, and is justified here only because the old behaviour destroyed or mislabelled data.

29. **End-to-end test wording updated after CI began running it (open, audit finding A7).**
- The Playwright test expected "Reported by 3+ students"; the product text became "Reported by 3+ people" in an earlier
  commit (dbe57b2) and the suite was not in CI, so nobody noticed. The test now matches the deliberate wording.
- Running it locally in the cloud sandbox is not possible (no matching browser build), so CI is the check for it.

30. **Rules B2 and B3 (open).**
- **Advance-fee wording (B2)** uses the existing strong tier (+30, blocks "likely legitimate"); no new weight. Patterns are
  directional on purpose ("we will send you a gift card" and "you will receive an OTP" do not match) and a negation cancels
  a match. Hand-derived eval cases EC46-EC50 include two false-alarm guards.
- **Link patterns (B3)** are informational (no score). A shortener or `@` in a link has many innocent uses, and a score
  would punish genuine recruiters. Redirect-following and TLS checks need network calls, so they sit with the optional,
  consented lookups (group C), not here.

31. **PDF forensics (B4) kept stateless and informational (open).**
- **No score:** edited or re-saved PDFs have many innocent causes; active content is rare in offer letters but still left
  informational until an independent test set shows how often it occurs in genuine ones.
- **Duplicate-PDF detection not built as a stored fingerprint:** remembering file hashes across users would be a new
  identifier store that docs/PRIVACY_DESIGN.md does not allow. Near-duplicate wording is already matched against
  consented community reports (MinHash shingles). Comparing files inside one multi-file check comes with B5.

32. **Multi-file intake (B5, part 1) (open).**
- **Joined, not scored per file:** a payment demand in any file makes the whole pack high risk, which matches how a person
  reads a pack. The cost is that one noisy file can colour the result.
- **.eml alone:** the sender-authentication check is about one message, so mixing an .eml with other files is refused (422)
  rather than guessed at. The existing "add more evidence" re-check still takes one file at a time.
- **Limits:** 5 files, 10 MB each, 50,000 characters of text in total.

33. **QR codes inside PDFs (B5, part 2) (open).**
    - **Scope:** the first 3 pages only, rendered in memory at 150 dpi, to bound time and memory. A UPI QR on page 4+
      is missed. Pages over the pixel limit are skipped.
    - **Fail-soft:** any render or decode error yields no QR lines; it never blocks an analysis.
    - **Same rule as images:** only `upi://` payloads are kept and count as a payment demand; other QR content is dropped.

34. **Careers-page check (B6) (open).**
    - **Informational only, off by default:** a page on a domain the sender controls is weak evidence, so it adds a
      sentence and never score. Absence is never reported.
    - **Wipro and Cognizant advisories not added:** Wipro's fraud page is blocked to automated readers
      (robots.txt), so I did not read it. Cognizant's page was read but names no official domain, so a
      domain-mismatch advisory would need an invented domain. Neither is listed; add them if you can confirm the
      domains by hand.

35. **Safety playbook (B7) (open).**
    - **Rule-based and fixed text:** steps are chosen from the checks found, never written from the offer. The old
      one-line portal note is kept for compatibility.
    - **"Call 1930" is a `tel:` link:** it helps on phones and does nothing on desktops. Say if you prefer plain text.
    - **Not covered:** no employer-specific reporting mailboxes (I would have to invent or hand-copy addresses),
      and no advice on chargebacks or bank-specific steps.

36. **Downloadable report (B8) (open).**
    - **Markdown, not PDF:** no new dependency and it opens anywhere; a PDF would need a library in the browser bundle.
      Say if you want a printable HTML or PDF version.
    - **Company name included** when the result shows one, since the report is for the person's own use or a complaint.
      Remove it if you would rather the file carried no names.
    - **Your edits (eb93c23, 5bc8719) were merged first;** I did not change them.

37. **Link lookups (group C) (open).**
    - **Web Risk only, no VirusTotal:** Web Risk's Lookup API is free to 100,000 calls a month (needs a Google Cloud
      project with billing enabled; no non-commercial clause appears on Google's pricing page). VirusTotal's free
      API is 500 requests a day, 4 a minute and barred from commercial products. Say if you want VirusTotal anyway.
    - **Informational, not scored:** "threat-listed" adds a note and the link safety step but no points, so no new
      weight needed. Scoring it later would need a documented weight, CLAIMS entry and trigger/non-trigger tests.
    - **One consent covers both** the Google lookup and the visit from our server, shown only if the operator turns
      the feature on. It is not remembered.
    - **Rebinding gap:** the public-address check and the connection resolve DNS separately. Fine for a small, opt-in
      feature; an egress proxy would close it.
    - **Uploads are in memory:** confirmed by search (no temp files or disk writes in the upload path), so no extra
      test was added, as you asked.

38. **Freshness panel and request budget (D) (open).**
    - **Thresholds:** 90 days for the registry snapshot and 180 for employer advisories are my guesses at "worth
      refreshing"; change `REGISTRY_STALE_DAYS` and `ADVISORY_STALE_DAYS` if you know better.
    - **Budget is per process and in memory:** it protects the free quota roughly, not exactly (restarts reset it,
      several workers each get their own). Only Web Risk is budgeted; the live registry lookup already has a 0.5 s throttle.
    - **Public endpoint:** `/sources` is unauthenticated and shows which optional lookups are on and the Web Risk
      usage count. It shows no keys. Say if you would rather hide the counts.

39. **Trust fixes after the external review (2026-11-24) (open).**
    - **Uploaded email headers are never proof.** A reported DMARC/DKIM pass is shown, never counted, and no longer
      lowers the score or supplies the external signal. Failures still count. Cost: a genuinely authenticated
      `.eml` (EC11) now lands in manual review instead of "likely legitimate". That is the intended trade: a forger
      can type a pass, so a pass cannot be evidence. EC11's expected band was re-derived by hand from the updated
      `risk_scoring.py` docstring, not edited to hide a failure; the old expectation is recorded in its basis text.
    - **A registry match needs a matching domain** (`identity_tie.py`: whole name, first distinctive word of 4+
      letters, or initials of 3+ words). Strict on purpose: real companies on unrelated or abbreviated domains
      (for example hcltech for "HCL Technologies") now get "verify manually". EC51 covers the caught case.
    - **EC41 stays a documented dangerous miss.** A scammer who registers a domain equal to the company's name
      passes this test. Closing that needs something we cannot check from text (who controls the domain).
    - **Seven existing tests or helpers were edited** because they encoded the old rule or built checks without a
      domain/company name: three about uploaded headers (test_audit_regressions, test_demo_documents,
      test_email_auth), one message string (test_community_reports), and three fixtures that now carry a matching
      domain and company (test_audit_regressions, test_scam_text, test_result_wording). No assertion about payment
      demands or wording was loosened; the only band changes are the two header cases above.

40. **Upload and request limits (open).**
    - **Numbers are my choices:** 52 MB request cap (5 x 10 MB plus form overhead), 60 native PDF pages, 90 s OCR
      deadline, 4 concurrent analyses, 3 s wait for a slot. Change them in `ingestion.py`, `email_auth.py` and the
      `MAX_REQUEST_BYTES` / `ANALYZE_CONCURRENCY` settings if your host is bigger or smaller.
    - **In-process limits are not isolation:** a worker process or container with a memory limit is still the
      right defence against a crafted file; these limits reduce the damage a single file can do.
    - **Concurrency is per process:** with N workers the real limit is N x 4.

41. **Outbound hardening (open).**
    - **My choices:** 8 s overall deadline for link checks, 5 link-checked analyses per connection per hour, a shared
      daily visit budget of 6000 (`LINK_VISIT_DAILY_BUDGET`). Change `LINK_CHECKS_PER_HOUR` if your users share an address
      (campus or office NAT would share one allowance).
    - **Per-process again:** budgets and allowances reset on restart and are per worker.
    - **Behind a proxy** the connection address seen by the app may be the proxy's; configure the host so the real
      client address reaches the app, or this cap applies to everyone together.
    - **Not run against real sites:** the pinned client is tested with mocked DNS and sockets only.

42. **Community reports and disputes hardening (open).**
    - **No true independence check exists.** Reporters are anonymous by design, so the gate is only "reports span 2
      different UTC days" (`MIN_DISTINCT_DAYS`). It stops a one-sitting burst, not a patient attacker. A real moderation
      queue would need a person doing the reviewing; I did not invent one.
    - **Template-wording matches are not gated** by the two-day rule (a single matching report still adds +25, as
      before). It can never produce high risk on its own, but one false report can flag lookalike letters.
    - **Numbers are my choices:** disputes active 90 days, deleted at 180; 3 open per address, 5 per indicator;
      `/indicators/stats` 30 per minute and `/disputes/verify` 10 per hour per address.
    - **Verification link changed:** emails now link to `/verify-dispute#token=...`; the old `GET /disputes/verify?token=`
      is gone. Links already emailed under the old format stop working (they expire in 24 h anyway).
    - **Test setup changed, assertions did not:** report fixtures now alternate today/yesterday so they meet the
      two-day gate; new tests cover the one-day burst (no points, not shown) and the two-day case.

43. **Privacy operations, deployment and dependencies (open).**
    - **Not run here:** the multi-stage Dockerfile (no container runtime in my environment), the Vercel headers, and the
      CSP in a real browser. Build the image once and click through every page before relying on them.
    - **CSP choices:** `style-src` keeps `'unsafe-inline'` (the page uses inline style attributes); scripts are `'self'`
      only. The Vercel copy allows `connect-src https:` because the backend address is not known to this repo;
      tighten it to the backend's address.
    - **HSTS** is opt-in (`HSTS_ENABLED=1`) on the app and always on in `vercel.json` (Vercel is https-only).
    - **Retention:** analysis rows 365 days (my choice; `ANALYSIS_RETENTION_DAYS`). Reverse-proxy logs are outside this repo.
    - **Dependencies:** `requirements.txt` keeps minimums (raised for python-multipart, pillow, pypdf, which I tested at
      the lock versions and the newest, not at the new floors); `requirements.lock` is exact and hashed for Python 3.11
      on Linux. Regenerate it with the command in its header; it does not cover Windows.
    - **CI:** read-only token, timeouts, run cancellation, and a second audit of the lock. I did not pin GitHub Actions
      to commit hashes.
    - **Downloads** now revoke the temporary link after 10 seconds instead of immediately.

44. **Copy and wording fixes (open).**
    - "Report this scam" is now "Share a suspected scam"; the .eml help no longer says we "verify who actually sent it"
      (a pass in an uploaded file is never counted). The mixed-.eml error now shows the server's own wording.
    - The upload label says "up to 5 files (PDF, image or .txt), or one .eml"; picking more than 5, or an .eml with other
      files, shows a note instead of silently dropping files.
    - **Left alone:** the `VITE_DEMO` sample buttons and "demo fixture" labels are off by default and point at files
      that no longer exist; I did not remove them because the frontend redesign will replace that screen.
