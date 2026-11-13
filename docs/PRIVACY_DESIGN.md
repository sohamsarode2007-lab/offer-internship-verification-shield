# Privacy design: scam indicator network and template matching

**Status: proposal for approval.** This document describes the intended design
for Prompt 5. No indicator-network implementation is included in this change.

## Data stored

For a report submitted with consent, the service stores only:

- HMAC-SHA256 digests of identifiers extracted by the analyzer, keyed by a
  secret pepper supplied through `INDICATOR_PEPPER` (never committed to the
  repository): UPI VPAs; bank account numbers paired with their IFSC; Indian
  phone numbers normalized to E.164; email addresses; and non-free-mail sender
  domains.
- A 128-value MinHash signature of normalized offer-letter text, using word
  5-shingles. The source text is used in memory to compute the signature and is
  then discarded; neither it nor its shingles are stored.
- The consent version and report metadata needed to count reports, enforce
  single use, and apply retention. Demo records are explicitly marked as demo.

The indicator store does not contain offer text, names, student/user identity,
or IP addresses. The database stores no raw indicator values. Normalization is
type-specific and deterministic before HMAC: for example, UPI VPAs are trimmed
and case-folded, Indian phones are normalized to E.164, and bank-account
digests include the normalized IFSC as well as the account number. HMAC inputs
are domain-separated by indicator type so that equal strings from different
types cannot be correlated accidentally. An unset `INDICATOR_PEPPER` must
disable report creation and matching rather than use a repository or default
secret.

MinHash is a compact probabilistic sketch of shingle overlap, not an encrypted
or reversible text representation. It contains neither the shingles nor their
order, and each of its 128 values is a minimum hash over a large set of 5-word
sequences. Recovering a unique source text from the signature is therefore not
practical. Similarity can still reveal that two letters share substantial
word-sequence structure; the signature is pseudonymous, so access and retention
controls still apply.

The report token carries only these hashes, the signature, and necessary
non-content metadata. It is signed, expires after 24 hours, and is single-use.
The server stores a token identifier or equivalent replay-prevention state;
token payloads and raw upload content must not be written to application logs.

## Consent

The report action requires an unchecked-by-default checkbox with this exact
wording, version `1`:

> I consent to share the scam indicators and a privacy-preserving signature of this offer with the service to warn other students. The offer text, names, and my identity will not be stored. I understand the indicators are pseudonymised and may be matched against future reports.

The submitted `consent_version` must equal `1`. Store that version alongside
each accepted report so the consent shown at submission can be audited. No
report is accepted without affirmative consent.

## Abuse resistance and scoring

- A report token is minted only by `/analyze`, from indicators and text the
  analyzer itself extracted. `/report` accepts no caller-supplied indicator
  values or signatures. One token can create at most one report.
- `/report` is rate-limited per source IP. IPs are used transiently by the
  limiter and are not saved in indicator/report records or application logs.
- Indicator counts affect a result only after at least three reports from
  distinct, single-use analysis tokens. Ten or more reports use the higher
  indicator weight. A lightly edited letter may match a reported scam template
  by MinHash LSH at similarity `>= 0.8`.
- “Independent” here means distinct analysis/report tokens, not verified
  distinct people. Because the design deliberately stores no student identity,
  it cannot prove that several tokens came from several people. Per-IP
  throttling and one-use tokens raise the cost of simple replay but do not
  eliminate coordinated or distributed poisoning. This limitation must be
  reflected in product wording and scoring confidence.
- Community matches are risk evidence only. They never count as external
  verification for the low-risk guard, and details disclose aggregate counts
  without exposing another report's content.
- Synthetic demo reports are marked `is_demo` and participate in lookups only
  while `DEMO_MODE=1`; they must not inflate production counts.

## Disputes and retention

A company can dispute an indicator through `/disputes`. The raw indicator value
is normalized and HMACed for lookup, then discarded. The indicator is marked
disputed and excluded from scoring while it awaits manual review. A contact
email is stored only for a dispute, to support follow-up; it is not copied to
reports, analyses, logs, or indicator records. Dispute reason text should not
be used to submit offer content or unrelated personal information.

Indicator records that have not been seen for 24 months are automatically
purged, including their associated signatures/counts where applicable. A
disputed indicator is excluded from scoring pending review; disputes do not
justify retaining its indicator past the stated 24-month inactivity limit.
The purge job must run automatically and be covered by a test.

`GET /indicators/stats` exposes aggregate counts only. It must not return
identifier hashes, signatures, report-level timestamps, or any report content.

## Threat model

| Attacker goal | Method | Mitigation | Residual risk |
| --- | --- | --- | --- |
| Poison a legitimate company's identifiers | Submit repeated false reports for a company's UPI ID, account/IFSC, phone, email, or domain | Only analyzer-extracted values can enter a report; one-use tokens; per-IP `/report` limit; minimum three distinct tokens; company disputes pause scoring | A determined attacker can create multiple analyses or distribute submissions across IPs. Token independence is not proof of distinct people; manual dispute review is required. |
| Enumerate whether a specific UPI ID was reported | Probe analyses and observe whether a match changes the result | HMAC-SHA256 with secret `INDICATOR_PEPPER`; never expose hashes or report contents; disclose only thresholded counts and generic match details; rate limits | Repeated adaptive probes may still reveal that a value crosses a threshold. Pepper compromise makes offline guessing of low-entropy identifiers more feasible. |
| Replay report tokens | Submit the same token repeatedly or after expiry | Signed token with 24-hour expiry; persist single-use token state and atomically consume it; reject invalid, expired, or reused tokens | Theft before first use can let another party consume the token; short expiry and TLS reduce but do not eliminate that risk. |
| Leak the pepper | Read environment/configuration, logs, backups, or process memory | Keep `INDICATOR_PEPPER` in deployment secret storage; never commit, log, return, or include it in database backups; restrict operational access and support rotation | Anyone obtaining the pepper and database can test guessed identifiers and correlate matching reports. Rotation complicates matching across key versions and may require retiring old digests. |
| Infer text from template signatures | Obtain stored MinHash signatures and attempt reconstruction or linkage | Store only 128 MinHash values, not text or shingles; restrict access; expire inactive records; return aggregate results only | Similarity/linkage between known documents can remain possible. MinHash is a pseudonymous similarity sketch, not a guarantee of anonymity. |
| Abuse disputes to suppress real scam indicators | File false disputes against a widely reported indicator | Exclude the disputed indicator only while pending manual review; authenticate and rate-limit dispute intake; keep auditable dispute status | Review delays may temporarily suppress a valid warning; a compromised dispute channel can still cause harm. |

## Honest limits and legal review

HMACed identifiers and MinHash signatures are **pseudonymised, not
anonymous**. Stable hashes allow matching over time, and template signatures
can reveal similarity. This design needs legal review under India's Digital
Personal Data Protection (DPDP) framework before deployment, including the
consent language, purpose, retention, dispute handling, and rights process.
The lack of raw offer text does not by itself establish that the stored data is
outside privacy law.

Reports are not independently verified findings. Thresholds reduce single
report influence but cannot guarantee that multiple tokens represent multiple
people. Students should see community matches as a warning signal, not proof
that an employer or identifier is fraudulent.
