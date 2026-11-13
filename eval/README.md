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
| EC01 | Passing demo domain offsets the +10 unverified GSTIN: subtotal 0; no registry/authenticated-sender signal triggers the guard floor of 31 | insufficient evidence, verify manually |
| EC02 | Payment +65; nearby urgency +20; +10 GSTIN and -10 domain: 85 | high risk |
| EC03 | Payment +65; +10 GSTIN and -10 domain: 65 | high risk |
| EC04 | Negated payment adds 0; +10 GSTIN and -10 domain: subtotal 0; external-verification guard floor 31 | insufficient evidence, verify manually |
| EC05 | Inbound stipend and negated fee add 0; +10 GSTIN and -10 domain: subtotal 0; external-verification guard floor 31 | insufficient evidence, verify manually |
| EC06 | Free-mail domain failure +30, GSTIN/free-mail consistency failure +25, and GSTIN PAN name-initial mismatch +10: 65 | high risk |
| EC07 | Missing registration +20; no usable domain and no registration +20: 40 | insufficient evidence, verify manually |
| EC08 | No payment demand, so urgency adds 0; +10 GSTIN and -10 domain: subtotal 0; no external signal raises score to 31 | insufficient evidence, verify manually |
| EC09 | Payment +65; missing registration +20; no usable domain and no registration +20; capped at 100 | high risk |
| EC10 | Missing registration +20; no usable domain and no registration +20: 40 | insufficient evidence, verify manually |

## Known limitation: urgency without payment

EC08 remains labelled `scam` (`soft_urgency`), and its actual band is now
`insufficient evidence, verify manually`. Urgency points still apply only when
urgency is near an already detected payment demand; a deadline by itself earns no
points. However, its structural-only evidence no longer qualifies as low risk.
The dangerous-miss count therefore drops from 1 to 0; EC08 is an abstention, not
a likely-legitimate result. The synthetic label is a fixture assumption, not
independent proof that a real offer with an acceptance deadline is fraudulent.

An independent deadline penalty is not needed to move EC08 out of the low-risk
band. Adding one could still over-flag legitimate offers with real acceptance
deadlines or expiring positions, so urgency alone continues to contribute no
points under the current scoring rules.

## Expected-band changes in this revision

The following expectations were hand-re-derived from the updated scoring rules
before running tests. Truth labels are unchanged.

| Cases | Previous band | New band | Reason |
|---|---|---|---|
| Eval EC01, EC04, EC05, EC08 | likely legitimate | insufficient evidence, verify manually | They have a passing domain and structurally valid GSTIN but no registry match or authenticated sender; the low-risk guard raises subtotal 0 to 31. |
| Regression tests using `GOOD` with only domain + valid GSTIN (negated fee, no fee, inbound stipend, recipient-email variant) | likely legitimate | insufficient evidence, verify manually | Structural evidence is insufficient without an external verification signal. |

The Emberlake demo document stays `likely legitimate` only when its opt-in
synthetic registry fixture is enabled; that result is explicitly labelled and is
not a claim of live MCA verification.

## Held-out rule

These synthetic edge cases are regression checks only. Keep them out of training,
weight selection, and threshold tuning; they are not a held-out accuracy set.
No real test set is included. If a separately sourced real evaluation set is
created later, freeze it before model or rule tuning, group duplicate or
near-duplicate records together, and hold out entire source groups so the same
publisher cannot appear in both development and evaluation data.
