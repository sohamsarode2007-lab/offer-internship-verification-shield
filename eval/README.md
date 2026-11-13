# Synthetic regression evaluation

`edge_cases.csv` contains only hand-authored synthetic regression cases. Every
row is marked `synthetic=true`; it is not a real-world benchmark and must not be
reported as one.

Run the local deterministic rule path (offline, using explicitly configured
`.example` demo fixtures):

```powershell
.\.venv\Scripts\python.exe eval\run_eval.py
```

To exercise a running API instead:

```powershell
.\.venv\Scripts\python.exe eval\run_eval.py --live --base-url http://127.0.0.1:8000
```

The output separates two questions: `label-vs-band` compares each declared truth
label with the actual risk band, while `expected-vs-actual` compares the band with
the hand-derived regression expectation. A row can be a dangerous miss and still
pass its expected-band check; both statuses are printed side by side. The report
also includes a truth-by-risk-band count matrix, false alarms, manual-review
abstention rates per class, and a per-`case_type` table. An expected-band mismatch
exits with status 1.

## Hand-derived expected bands

`expected_band` was re-derived from the fixed weights and band boundaries in
`app/services/risk_scoring.py`'s docstring. `expected_basis` in the CSV records the
arithmetic for each row. The evaluator requires that field and never calculates
or updates expected bands from predictions.

| Case | Hand calculation from the scoring table | Expected band |
|---|---|---|
| EC01 | Passing demo domain offsets the +10 structurally valid but unverified GSTIN: 0 | likely legitimate |
| EC02 | Payment +65; nearby urgency +20; +10 GSTIN and -10 domain: 85 | high risk |
| EC03 | Payment +65; +10 GSTIN and -10 domain: 65 | high risk |
| EC04 | Negated payment adds 0; +10 GSTIN and -10 domain: 0 | likely legitimate |
| EC05 | Stipend VPA is inbound and fee mention is negated; +10 GSTIN and -10 domain: 0 | likely legitimate |
| EC06 | Free-mail domain failure +30 and GSTIN/free-mail consistency failure +25: 55 | insufficient evidence, verify manually |
| EC07 | Missing registration +20; no usable domain and no registration +20: 40 | insufficient evidence, verify manually |
| EC08 | No payment demand, so urgency adds 0; +10 GSTIN and -10 demo domain: 0 | likely legitimate |
| EC09 | Payment +65; missing registration +20; no usable domain and no registration +20; capped at 100 | high risk |
| EC10 | Missing registration +20; no usable domain and no registration +20: 40 | insufficient evidence, verify manually |

## Known limitation: urgency without payment

EC08's synthetic ground-truth label is `scam` (`soft_urgency`), but its actual
band is `likely legitimate`. The rules add urgency points only when urgency is
near an already detected payment demand; a deadline by itself earns no points.
The expected band is still `likely legitimate` because that is what the documented
scoring table produces. Thus EC08 is both a **dangerous miss** against its label
and a **passing regression expectation**; these are separate comparisons.

A small candidate rule would add an independent +31-point manual-review signal
for deadline/expiry language such as “position expires” even without a payment
demand. That would move EC08 from 0 to 31, but it changes the existing EC08
expected-band regression. It could also send legitimate offers with real
acceptance deadlines or expiring positions to manual review. The rule is not
implemented; changing existing regression behavior requires an explicit decision
about that trade-off.

## Held-out rule

These synthetic edge cases are regression checks only. Keep them out of training,
weight selection, and threshold tuning; they are not a held-out accuracy set.
No real test set is included. If a separately sourced real evaluation set is
created later, freeze it before model or rule tuning, group duplicate or
near-duplicate records together, and hold out entire source groups so the same
publisher cannot appear in both development and evaluation data.
