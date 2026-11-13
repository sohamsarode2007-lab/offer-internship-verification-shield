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

The output contains a truth-by-risk-band confusion matrix in counts, dangerous
misses (scam cases scored `likely legitimate`), false alarms (legitimate cases
scored `high risk`), manual-review abstention rates per truth class, and band
counts plus expected-band matches by `case_type`. A mismatch exits with status 1.

## Held-out rule

These synthetic edge cases are regression checks only. Keep them out of training,
weight selection, and threshold tuning; they are not a held-out accuracy set.
No real test set is included. If a separately sourced real evaluation set is
created later, freeze it before model or rule tuning, group duplicate or
near-duplicate records together, and hold out entire source groups so the same
publisher cannot appear in both development and evaluation data.
