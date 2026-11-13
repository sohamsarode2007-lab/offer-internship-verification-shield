# Quarantined training and scraped data

These CSVs are retained locally for auditability but are ignored by Git because
scraped complaint text can contain real people's names, contact details, and
other identifying information. They must not be used as clean ground truth or
committed to the repository.

## Audit findings

The requested pandas check could not run on this Windows host: pandas' compiled
extension was blocked by Windows Application Control (`DLL load failed while
importing pandas_parser`). The following counts were independently cross-checked
with Python's standard-library CSV reader over every row. No dataset labels or
rows were changed during this audit; the originals are preserved here.

### Legit class source mix

The `label=0` class is mostly remote job-posting descriptions, not Indian offer
letters. Counts are grouped by source portal; the 12 template rows are shown
separately because they did not come from those portals.

| Dataset | Arbeitnow | Jobicy | Remotive | Agent-written templates | Total legit rows |
|---|---:|---:|---:|---:|---:|
| `legit_offers_raw.csv` | 176 | 50 | 18 | 12 | 256 |
| `benchmark_dataset_v1.csv` | 151 | 50 | 18 | 12 | 231 |

All 12 template rows came from `AUTHENTIC_OFFER_TEMPLATES` in the collector.
They were written by an agent and used invented URLs; they are not authentic
offers or source-verified records. The collector no longer adds them.

### Reddit sample review

A uniform random sample of 30 rows from `reddit_scams_raw.csv` was selected with
Python `random.Random(42).sample` and read by hand. **5 of 30** described a
specific recruitment scam (a deceptive course-fee demand, interview-payment
demand, or concrete nonpayment/reimbursement scheme). General complaints,
questions asking whether something was a scam, suspicions without a concrete
deceptive act, and headline-only claims were not counted. This is a small manual
audit, not a reliable estimate for the entire Reddit collection.

### ConsumerComplaints truncation

Rows were counted as truncated when their `text` field contains the literal
`...` marker.

| Dataset | ConsumerComplaints rows | Rows with `...` | Share |
|---|---:|---:|---:|
| `scam_dataset.csv` | 261 | 203 | 77.8% |
| `benchmark_dataset_v1.csv` | 254 | 196 | 77.2% |

## Conclusion

A classifier trained on these labels would learn source and geography patterns
as much as (or more than) scam-vs-legitimate evidence: the legitimate class is
dominated by European/US remote postings, while the Reddit and ConsumerComplaints
classes are noisy, many complaint rows are truncated, and some nominally
legitimate rows are invented templates. These data do not support a credible
real-world accuracy claim.
