# Synthetic regression evaluation

`edge_cases.csv` contains only hand-authored synthetic regression cases. Every
row is marked `synthetic=true`; it is not a real-world benchmark and must not be
reported as one.

Rows with `input_type=eml` reference the synthetic RFC 5322 messages in
`tests/fixtures/eml/`; the local evaluator parses those messages and feeds PDF
attachments through the same ingestion path as `/analyze`.

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
| EC06 | Free-mail domain failure +30, GSTIN/free-mail consistency failure +25, and PAN-initial mismatch +10: 65. By hand, the weighted mod-36 sum for the first 14 GSTIN characters is 181; 181 mod 36 = 1, so the expected final character is Z. The GSTIN checksum passes and the PAN initial Z conflicts with claimed company initial A. | high risk |
| EC07 | Missing registration +20; no usable domain and no registration +20: 40 | insufficient evidence, verify manually |
| EC08 | No payment demand, so urgency adds 0; +10 GSTIN and -10 domain: subtotal 0; no external signal raises score to 31 | insufficient evidence, verify manually |
| EC09 | Payment +65; missing registration +20; no usable domain and no registration +20; capped at 100 | high risk |
| EC10 | Missing registration +20; no usable domain and no registration +20: 40 | insufficient evidence, verify manually |
| EC11 | +10 unverified GSTIN and -10 passing From domain = 0; aligned authenticated sender meets guard | likely legitimate |
| EC12 | DMARC fail +30 and body/From domain mismatch +15; base 0; total 45 | insufficient evidence, verify manually |
| EC13 | Mismatched Gmail Reply-To +25; failed auth signal does not meet guard; 25 is raised to 31 | insufficient evidence, verify manually |
| EC14 | Protected-brand display spoof +25; failed auth signal does not meet guard; 25 is raised to 31 | insufficient evidence, verify manually |
| EC15 | Topmost DMARC fail +30; forged lower pass ignored; guard raises 30 to 31 | insufficient evidence, verify manually |
| EC16 | No Authentication-Results gives no points; no external signal raises 0 to 31 | insufficient evidence, verify manually |
| EC17 | PDF attachment exposes a payment demand; +65 hard floor | high risk |
| EC18 | Three matching indicators contribute +25; matching reported template +25; community cap gives +40. Missing registration +20 and passing demo domain -10 give 50 | insufficient evidence, verify manually |
| EC19 | Payment demand +65; missing registration +20; passing domain -10; correlated community evidence +40; subtotal 115 capped at 100 | high risk |
| EC20 | Synthetic registry: active, name-matched CIN gives a registry pass; 0 points; the -10 offsets have nothing to offset; the registry match satisfies the low-risk guard | likely legitimate |
| EC21 | Synthetic registry: CIN belongs to a Struck Off company, registration fail +25; passing demo domain -10; subtotal 15; guard raises to 31 because the registration failed | insufficient evidence, verify manually |
| EC22 | Synthetic registry: CIN is registered to a different company (Ashcombe Data Labs), registration fail +25; passing demo domain -10; subtotal 15; guard raises to 31 | insufficient evidence, verify manually |
| EC23 | Inbound stipend and negated fee add 0; domain pass and registry match have nothing to offset; registry match meets the guard: 0 | likely legitimate |
| EC24 | "daily tasks include" is not a paid-task pattern: 0; registry match meets the guard | likely legitimate |
| EC25 | Negated Telegram and negated fee wording add 0; registry match meets the guard: 0 | likely legitimate |
| EC26 | Moderate chat wording +15; domain pass -10 leaves 5; registry -10 but only 5 remain: 0. The moderate tier does not block the legitimate band | likely legitimate |
| EC27 | High-pay note is informational: 0; registry match meets the guard | likely legitimate |
| EC28 | Odd-phone note is informational: 0; registry match meets the guard | likely legitimate |
| EC29 | Moderate chat wording +15; unverified GSTIN +10; domain pass -10: 15; no external signal raises it to 31 | insufficient evidence, verify manually |
| EC30 | Udyam format valid but unverified +10; domain pass -10: 0; no external signal raises it to 31 | insufficient evidence, verify manually |
| EC31 | Strong tier +30 and chat wording +10 extra; missing registration +20; no usable domain and no registration +20: 80 | high risk |
| EC32 | Strong tier +30 (or payment +65 if it also fires); +20; +20: at least 70 | high risk |
| EC33 | Moderate tier +15; +20; +20: 55 | insufficient evidence, verify manually |
| EC34 | Moderate tier +15 (one family counts once); +20; +20: 55 | insufficient evidence, verify manually |
| EC35 | UPI link is a payment demand +65; +20; +20: 105, capped at 100 | high risk |
| EC36 | Payment +65 is never offset; unverified GSTIN +10 and domain pass -10 cancel: 65 | high risk |
| EC37 | Disposable mailbox +30; unverified GSTIN +10; no offset: 40 | insufficient evidence, verify manually |
| EC38 | Labelled PAN fails format +25; domain pass -10: 15; registration failed, so the guard raises it to 31 | insufficient evidence, verify manually |
| EC39 | Strong tier +30; domain -10; registry -10: 10; strong task-scam wording blocks the legitimate band, raising it to 31 | insufficient evidence, verify manually |
| EC40 | No rule matches Hinglish wording: +20; +20: 40 | insufficient evidence, verify manually |
| EC41 | Copied real CIN and a passing domain: 0; registry match meets the guard | likely legitimate |

EC20–EC22 (`registry_fixture=true`, `input_type=text_file`) read the demo offers in
`fixtures/demo/` and run with the synthetic company master
(`fixtures/demo/synthetic_mca_master.csv`, fictional companies only) loaded into a
temporary SQLite file in `DEMO_MODE`. All other cases run with no registry loaded.
EC21 and EC22 are labelled `scam` but land in the manual-review band: a registry
failure alone is worth +25, so without a payment demand they are abstentions, not
high risk. That is the documented behaviour, not a miss.

EC18 and EC19's `community_fixture=true` flag causes the local evaluator to seed three
synthetic scam reports in an ephemeral SQLite database through the same
single-use token and consent service flow. Its expected band was calculated
from the documented scoring weights before evaluation. EC18 is the sole existing
expectation that changed: `high risk` to `insufficient evidence, verify manually`
because correlated indicators and a template match now contribute only +40 total
(20 - 10 + 40 = 50). EC19 is a new payment-demand case; its payment signal still
forces high risk even with community evidence present. No other expected bands
changed.

Step 0 hand re-derivation: the PAN-initial rule now runs only after checksum
success. EC06 remains high risk because its checksum passes (weighted sum 181,
remainder 1, expected final character Z), so the mismatch contributes +10. The
incorporation contradiction rule adds no points to existing cases because none
claims a founding year or company age. No existing expected band changed in Step
0. EC11–EC17 are new synthetic email cases with expectations worked from the
updated docstring before evaluation; truth labels remain synthetic assumptions.

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

The Emberlake demo document stays `likely legitimate` only when the synthetic
company master is loaded in `DEMO_MODE`; its companies are fictional and the
result is not a claim of live MCA verification.

## Held-out rule

These synthetic edge cases are regression checks only. Keep them out of training,
weight selection, and threshold tuning; they are not a held-out accuracy set.
No real test set is included. If a separately sourced real evaluation set is
created later, freeze it before model or rule tuning, group duplicate or
near-duplicate records together, and hold out entire source groups so the same
publisher cannot appear in both development and evaluation data.

## EC23-EC41: added with the scam-chat, UPI, advisory-adjacent and format rules

These 19 cases were added after the scam-chat wording, UPI/QR, disposable-mailbox and PAN/Udyam rules.
Each expected band was derived by hand from the scoring docstring before the evaluator was run; all 19
matched on the first run and no earlier expectation changed. They are still hand-written regression
cases (`synthetic=true`), not a held-out accuracy set.

- **False-alarm guards (EC23-EC28):** genuine-looking offers that mention UPI stipends, "daily tasks",
  negated Telegram/fee wording, WhatsApp scheduling, a high package, or an odd phone number must stay
  "likely legitimate". They fail loudly if a new rule starts flagging ordinary wording.
- **New rules firing (EC31-EC39):** task scams, pay-to-withdraw, chat-only, no-interview, UPI links,
  disposable mailbox and a bad PAN.

### Known gaps, recorded on purpose

- **EC41 is a dangerous miss and is expected to be.** A scam that copies a real registered company's
  CIN and uses a domain that passes every check looks identical to a genuine offer to everything this tool
  can see. The summary line "1 dangerous miss(es)" is that case; do not "fix" it by loosening the guard.
- **EC40:** the wording rules are English only, so a Hinglish task scam gets no rule points and abstains.
- **EC33, EC34 (and EC21, EC22 earlier):** scams with only moderate evidence land in manual review rather
  than "high risk"; that is the intended behaviour, not a miss.
