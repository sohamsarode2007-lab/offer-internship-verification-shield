# Privacy design: scam indicator network and template matching

**Status: implementation specification.** The service warns students using only
scammer-role indicators selected by the reporting student and a redacted
template signature. This is not proof that a person or company is fraudulent.

## What is stored

For an explicitly consented report, store HMAC-SHA256 digests of only the
selected, analyzer-extracted identifiers, keyed by `INDICATOR_PEPPER` (a
deployment secret, never stored in the repository):

- UPI VPAs and bank account numbers paired with their IFSC, but only in a
  payment-demand context;
- Indian phone numbers normalized to E.164, but only in a contact context such
  as “call/WhatsApp/contact HR”;
- the sender address/domain (authenticated `From` for `.eml`, contact-line
  addresses/domains otherwise); free-mail sender domains are excluded.

The analyzer must distinguish scammer-role values from candidate details.
Identifiers on To/Cc/Dear lines and in the candidate's own details are never
eligible. Before consent, show a masked list of the exact eligible indicators
and let the student deselect any value. Only selected values are included in
the report token and stored. Normalization is type-specific; UPI and email are
trimmed and case-folded, phones are normalized to E.164, and account digests
include the normalized IFSC. HMAC inputs are domain-separated by indicator
type. Every digest records `key_version`.

Store a 128-value MinHash signature based on word 5-shingles, but first replace
names, emails, phone numbers, UPI IDs, account numbers, amounts, and dates with
fixed placeholders. The source text and shingles exist only in memory and are
discarded. MinHash stores minima over hashed shingles, not the shingles or
their order; with only 128 values it is not practical to reconstruct a unique
source text. A signature can still reveal similarity to known text, so it is
pseudonymous and access/retention controls still apply.

The database also stores consent version, timestamps and report metadata
needed for count/withdrawal/retention, and an `is_demo` flag for synthetic demo
reports. It stores no offer text, names, student identity, raw indicator
values, or IP addresses. The only contact email stored is the contact address
on a dispute, retained until 12 months after that dispute is resolved.

### Per-indicator data for the public scam-trends page (consented reports only)

For each indicator the student selects in a **consented** report, store exactly:

| Field | Content |
| --- | --- |
| type | `email`, `domain`, `upi`, `phone` or `bank` |
| digest | the existing peppered HMAC (with `key_version`) |
| masked display form | the same masking the student saw in the report flow: email `pl•••@gmail.com` (first 2 characters of the local part), UPI `careerd•••@ybl` (first 7 characters), phone `+91 ••••••1234`, bank `••••1234 + IFSC`; at least one character of a short local part is always hidden, so a full address or UPI ID is never shown. **Only a non-free-mail sender domain is shown in full** (free-mail domains are never extracted as domain indicators). |
| ISO week | `YYYY-Www` of the report |
| scam category | the rule-based category of the analysed letter |

Raw email addresses, phone numbers, UPI IDs and account numbers are **never
stored**; the masked form is computed in memory and is the only readable form
kept. A normal `/analyze` stores none of this: indicators are written only when
a student consents to a report. Withdrawing a report deletes its indicators.

### Anonymous trend counts (every check)

**Purpose:** anonymous weekly trend counts for the public scam-trends page
(the 12-week results chart and the category summary).

Every successful `/analyze` call records exactly **one** aggregate row with
three fields only:

| Field | Content |
| --- | --- |
| ISO week | `YYYY-Www` (no date or time) |
| risk band | likely legitimate / insufficient evidence / high risk |
| scam category | one rule-based category, e.g. `registration_fee` |

The row has no offer text, no indicators or identifiers, no file name, no
company name, no IP address and no link to the analysis record, a report or
a person. The category is computed in memory from the check results and the
text, which are then discarded as before. Because the row is unlinked, a
report withdrawal does not remove it. Checks made with `DEMO_MODE=1` are
flagged demo and count only in demo mode.

**Disclosure:** the scam-trends page and its CSV export show these counts
only as aggregates, and every count below five is shown as `<5`.
**Retention:** rows older than 24 months (by ISO week) are deleted by the
same hourly retention worker.

The public scam-trends page lists a sender only after **3 or more**
distinct consented reports of the same indicator, showing its masked form,
type, report count, first and last week, most common category and dispute
status. Senders with fewer reports never appear. The CSV export contains the
same fields only. Only reports given under consent version 4 (which says the
public scam-trends page shows them) are shown there.

If `INDICATOR_PEPPER` is unset, report creation and matching are disabled; do
not fall back to a checked-in or default secret. Rotation assigns a new
`key_version`: new reports use the new pepper, while old digests remain
matchable with their original version until they expire. Retire an old pepper
only after all digests using that version have expired or been removed.

## Consent

Before the report is sent, show the exact masked selected indicators. Require
an unchecked-by-default checkbox with this exact wording, version `4`:

> Share these details to warn other job seekers: the payment and contact details you selected above, and a scrambled fingerprint of the letter's wording with names and numbers removed. We don't store the letter, your name or your contact details. You can withdraw this report later with the code we give you. The public scam-trends page will show these details in masked form so it can warn other job seekers.

Store `consent_version=4` with each accepted report. Only version 4 is
accepted; versions 1 to 3 are obsolete (version 3 named a single college
instead of the public scam-trends page). No report is accepted without affirmative consent.

The response to `/report` includes a one-time withdrawal code. `POST
/report/withdraw {code}` is the report consent-withdrawal mechanism: it deletes
that report's contributions and decrements its counts. The code is shown once;
store only a verifier, not the plaintext code.

## Link lookups (optional, consented per check)

Decision: link lookups are off unless the operator sets `LINK_LOOKUPS=1`, and even then run only when the person
ticks an unchecked-by-default box on that check (wording: `LINK_CONSENT_TEXT` in `frontend/src/consent.ts`). The
consent covers that one check and is not remembered or stored.

- **What leaves the server:** for at most 3 links, a minimised web address (scheme, host and a short path; never the
  query, fragment, login part, or a path that looks like it holds an email, a name-like `@` or an 8+ digit number)
  goes to Google Web Risk with the operator's API key. Raw IP addresses are dropped. Nothing else from the offer is sent.
- **What the server does:** it makes a HEAD request to each link (public addresses only, at most 4 redirects, no
  body read) and reads the TLS certificate. The site's owner can see that a server opened the link; the person's own
  address is never involved. Each connection's hourly allowance is counted in memory under a one-way hash of its
  address and is never written to disk or logs.
- **What is kept:** nothing. Links and results are not stored or logged (log lines carry only an error type).
  Results appear as informational notes with no score effect, naming hosts only.
- **Honest limits:** the only outcomes are "threat-listed" or "unknown". "Not listed" is never shown as safe. DNS can
  change between our address check and the visit (rebinding); a hardened egress proxy would be the next step.
  A lookup to Google is a transfer to a third party; keep the switch off if that is not acceptable for your deployment.

## Abuse resistance, matching, and disclosure

- A signed, single-use `/analyze` report token expires after 24 hours. Before
  consent it contains only eligible candidate indicator digests, key versions
  and the redacted MinHash signature; it contains no raw identifiers. `/report`
  accepts no caller-supplied identifiers or signatures and persists only the
  digest selections the student confirms. Reject missing consent,
  expired/tampered/reused tokens, and selections not present in the token.
- `/report` and `/disputes` are rate-limited per source IP. IP state is
  transient limiter state only, is not copied to application logs/database,
  and is purged within 24 hours of the last request (or sooner when the limiter
  expires its window). Single-use token state is purged 48 hours after token
  expiry.
- Only distinct accepted report contributions count. They are not verified
  distinct people: no user identity is retained. Per-IP limits and one-use
  analysis tokens make simple replay harder but cannot stop coordinated or
  distributed poisoning.
- Indicator counts affect scoring only at 3 reports (3–9: +25) and 10 reports
  (+40). Template similarity >= 0.8 to a reported scam adds +25. Because these
  signals are correlated, the community contribution is the highest indicator
  bucket plus any template match, capped at +40 total; matching more identifiers
  never stacks. Community evidence alone cannot produce high risk: if community
  evidence alone crosses 60, cap the result at manual review with the factor
  “Reported by other job seekers; not enough independent evidence to call this high
  risk.” Neither community signal satisfies the external-verification low-risk
  guard. These limits address the [poisoning threat](#poisoning-a-legitimate-companys-identifiers).
- Details use buckets only: “reported by 3+ people” or “reported by 10+
  people”; never disclose exact counts or other reports' contents. `/indicators/stats`
  is aggregate-only and suppresses cells below 5.
- Synthetic demo reports are marked `is_demo` and participate only when
  `DEMO_MODE=1`; they never inflate production counts.

## Disputes and retention

Disputes are rate-limited. A dispute does not automatically suppress an
indicator: its score remains active and its detail adds “disputed by the
company, under review”. The exception is a domain dispute verified by a
one-time link sent to an address at that same domain; that domain may be
suppressed while pending manual review. Store the dispute contact email only
for follow-up, and delete it 12 months after resolution. The dispute reason
is a fixed code (our_business_detail, reported_in_error, someone_else_misused_it, other), never free
text, so offer text and unrelated personal information cannot be submitted. Migration 008 overwrote
free-text reasons stored earlier.

Anonymous trend rows (ISO week, band, category) are deleted 24 months after
their ISO week. Indicators and their report contributions not seen for 24 months are deleted
automatically. Report-level withdrawal removes that report's contribution
immediately. Dispute state does not exempt records from the 24-month
inactivity rule. An application retention worker runs hourly, and requests
also trigger a purge. Token replay state is purged 48 hours after token expiry.
Limiter IP state is transient and expires with its rate-limit window, with a
24-hour maximum retention.

## Threat model

### Poisoning a legitimate company's identifiers

Correlated identifiers can arise from the same report and template; they are
therefore capped together. Multiple matching contact/payment values are not
independent evidence that the offer is fraudulent.

| Attacker goal | Method | Mitigation | Residual risk |
| --- | --- | --- | --- |
| Poison a legitimate company's identifiers | Submit repeated false reports for a company's payment/contact identifiers | Only analyzer-extracted scammer-role values can be selected; student previews and can deselect; one-use tokens; per-IP limits; score thresholds; disputes; domain suppression only after same-domain email verification | Distinct tokens do not prove distinct people; distributed attackers can still poison. A verified domain dispute can temporarily hide a true warning pending review. |
| Enumerate whether a specific UPI ID was reported | Probe analyses and observe score/details | Secret peppered HMACs; never expose hashes or exact counts; bucketed details; suppress aggregate stats cells below 5; rate limits | Adaptive probes can reveal threshold crossings. Compromised pepper enables guessed-value checks against database digests. |
| Replay a report token | Re-submit token or withdrawal code | Signed 24-hour report tokens; atomic single use; replay-state purge after 48 hours; withdrawal code verifier is single-use | Theft before consumption can submit/withdraw once; short expiry and TLS reduce but do not eliminate theft risk. |
| Leak or rotate the pepper unsafely | Access configuration/database or discard an active key version | Deployment secret storage, no logging/committing; per-digest key version; old key retained only until associated digests expire | Database plus pepper permits guessing low-entropy identifiers. Key rotation requires retaining old keys and complicates operations. |
| Infer wording from template signatures | Obtain signatures and compare against known letters | Redact names, emails, phone, VPA, accounts, amounts and dates before MinHash; store only 128 values; access controls and expiry | Signature linkage and similarity inference remain possible; it is pseudonymous, not anonymous. |
| Abuse disputes to suppress scam reports | File false company disputes | Disputed indicators keep scoring; only a domain verified through a same-domain one-time link is temporarily suppressed; rate limits and review | Validly controlled domains can still suppress their domain temporarily while review is pending. |
| Harvest a candidate's own details | Place candidate email/phone in a letter and induce reporting | Role-based extraction excludes To/Cc/Dear lines and candidate details; only eligible masked values are selectable; tests enforce exclusions | Ambiguous or deliberately misleading prose may still confuse extraction, so student review and deselection remain necessary. |
| Read the reported-senders list | Open the public scam-trends page or its CSV export | Masked forms only; a sender appears only at 3+ consented v4 reports; disputes shown; CSV cells starting with `=`, `+`, `-` or `@` are prefixed to prevent spreadsheet formula injection | **There is no staff login yet** (single-college simulation; login is future scope), so anyone who can reach the site can read the masked list. Full sender domains are visible by design. |

## Honest limits and legal review

HMACed identifiers and MinHash signatures are **pseudonymised, not
anonymous**. Stable digests permit matching over time; signatures reveal
similarity. Some indicators are personal data of third parties (the senders),
which needs its own lawful-basis assessment. This design requires legal review
under the DPDP Act, 2023 and its Rules before deployment, including consent,
purpose, retention, third-party sender data, disputes, withdrawal, and rights
handling. Removing raw offer text does not by itself establish that stored
data is outside privacy law.

Community matches are not independently verified findings. Thresholds and
consent do not guarantee that reports describe scams or represent distinct
people. Students should treat a match as a warning to verify independently,
not proof that an employer or identifier is fraudulent.
