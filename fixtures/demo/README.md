# Demo documents (synthetic)

## Run the demo

From the repository root, in a fresh Command Prompt or PowerShell window:

```bat
run_demo.bat
```

Then open **http://127.0.0.1:8000** (the script prints the URL and opens it in your default
browser once the server answers). Stop it with Ctrl+C.

The script needs `.venv` (Python 3.11 with `requirements-dev.txt`) and Node.js on PATH; it stops
with a message if either is missing. It sets demo mode and the demo domains, builds the synthetic
company registry, seeds the simulated reports (safe to repeat), builds the frontend with
the sample buttons only when it is missing or out of date, and starts one server for the API and
website. Demo state lives in the git-ignored `data/demo/` folder; delete it to start fresh (the
simulated reports are dated relative to the day they are first seeded).

Suggested walkthrough (use the "Try a sample" buttons, or upload the matching PDFs below):

1. **Emberlake offer**: registry match, demo domain and no fee: 0, Likely legitimate. "Why" lists
   what was verified; there is no "Report this scam" button for a likely-legitimate result.
2. **Brightpath internship**: genuine-looking startup with no registration number: 31,
   Insufficient evidence ("Verify manually before you proceed").
3. **Tarnwick internship**: the CIN belongs to a struck-off company: 31, Insufficient evidence.
4. **Government scheme**: fee demand with UPI details and a deadline: 100, High risk.
   Then click **Report this scam** to show the consented report flow (consent version 3 tells
   the student that the public scam-trends page shows the details in masked form).
5. **Check → scam-trends page**: click **Corvane internship**. It asks for a security
   deposit via UPI to `careerdesk.fees@ybl`, a sender other job seekers already reported: 100,
   High risk, and "Why" shows **Reported by 3+ people**.
6. Open **Scam trends**. The same sender, `careerd•••@ybl`, is in **Reported
   senders** (6 reports; 7 if you reported it in step 5). The table lists only senders with
   3 or more reports; the simulated sender with 2 reports is not shown, and one sender is marked
   "Disputed by the company, under review".
7. Click **Export warning list** to download the same list as CSV (masked forms only).
8. **How it works**: what each check does and does not prove.

Tell your audience that every company in the demo is fictional. The PDFs have a real text layer,
so PDF uploads need no OCR. Image uploads (PNG/JPG scans) need Tesseract OCR installed locally
(for example the UB-Mannheim Windows build, or set `TESSERACT_CMD` to `tesseract.exe`).

## Files

Every document and data file in this folder is **synthetic**. Every company, scheme, person,
registration number, phone number, account number and domain in them is fictional.

| File | Pattern it demonstrates |
|------|-------------------------|
| `legit_emberlake.txt` / `.pdf` | Established private company: valid-structure GSTIN + CIN, company domain, explicit no-fee statement |
| `legit_brightpath_young_startup.txt` / `.pdf` | Genuine-looking young startup with no GST registration (below threshold) |
| `scam_fake_govt_scheme_fee.txt` / `.pdf` | Fake government scheme demanding a "refundable" verification fee via bank/UPI, with urgency |
| `registry_name_match_quillmere.txt` / `.pdf` | CIN matches an active company with the same name in the synthetic registry |
| `registry_struck_off_tarnwick.txt` / `.pdf` | CIN belongs to a company whose registry status is Struck Off |
| `registry_cin_mismatch_halvorn.txt` / `.pdf` | Offer claims one company but quotes the CIN of a different company |
| `scam_shared_upi_corvane.txt` / `.pdf` | Deposit demand to a UPI ID other (simulated) job seekers already reported |
| `simulated_senders.csv` | Simulated reports for the scam-trends page |
| `synthetic_mca_master.csv` | Synthetic company master: 13 fictional companies for the registry demo |

## Synthetic company registry

`synthetic_mca_master.csv` contains **fictional companies only** (invented names, made-up CINs
in the real CIN format, mixed Active / Struck Off / Dissolved / Under Liquidation statuses).
It is not MCA data. The official MCA company-master snapshot is future scope: its bulk
download requires eKYC, which this project has not completed.

Load it with the `--synthetic` flag (the loader refuses this file without it):

```powershell
.\.venv\Scripts\python.exe scripts\load_mca_master.py fixtures\demo\synthetic_mca_master.csv --synthetic --db data\demo_registry.sqlite3
$env:MCA_DB_PATH = "data\demo_registry.sqlite3"
$env:DEMO_MODE = "1"
$env:DEMO_FIXTURE_DOMAINS = "emberlakeanalytics.example,brightpathedtech.example,quillmeresoftware.example,tarnwicklogistics.example,halvornfintech.example"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The database records `source=SYNTHETIC`; the app uses it only when `DEMO_MODE=1` and
otherwise behaves as if no registry is loaded. On the website, results appear like any
registry result ("Company registry match: name; Active; incorporated date", or a failure that
leads with the problem, e.g. "Company is Struck Off in company registry records: ...") with no
synthetic label; the API response carries `registry_source: "synthetic"` for traceability.
Tell your audience that the demo companies are fictional.

Expected results with the settings above:

| Document | Score | Band |
|---|---|---|
| `registry_name_match_quillmere.txt` | 0 | likely legitimate |
| `registry_struck_off_tarnwick.txt` | 31 | insufficient evidence, verify manually |
| `registry_cin_mismatch_halvorn.txt` | 31 | insufficient evidence, verify manually |
| `legit_emberlake.txt` | 0 | likely legitimate (unchanged) |
| `legit_brightpath_young_startup.txt` | 31 | insufficient evidence, verify manually (unchanged; no CIN) |

Notes:

- The Emberlake GSTIN `07AAFCE4321L1ZO` passes the official check-character test, but it is
  **not** verified as a real registration. The system does not query live GST/MCA data.
- The synthetic company register above is the only demo registry path. Emberlake's CIN is
  one of its rows, so with the synthetic database loaded in `DEMO_MODE=1` Emberlake scores
  0 (`likely legitimate`). With only a demo-domain pass and a checksum-valid GSTIN (no
  registry loaded), Emberlake is capped at `insufficient evidence, verify manually`.
- Company domains use the reserved `.example` TLD, which **never resolves** in DNS. For a demo,
  run the backend with `DEMO_MODE=1` and
  `DEMO_FIXTURE_DOMAINS=emberlakeanalytics.example,brightpathedtech.example`.
  The domain check then returns `pass`, and its details start with
  `[DEMO FIXTURE — not a live DNS result]`, so the output always says it is a fixture.
- Without `DEMO_MODE`, the `.example` domains fail the MX check (NXDOMAIN), which is the correct
  live behaviour.
- `simulated_senders.csv` defines the simulated reports: 8 **fictional** senders
  (a made-up gmail.com recruiter address, two lookalike `.example` domains, two UPI IDs, a phone
  number, a disputed domain and one sender with only 2 reports), 45 reports in all, spread over
  the last 12 weeks in campaign-like waves. With `DEMO_MODE=1` and an environment-provided
  `INDICATOR_PEPPER`, `python scripts/seed_demo_reports.py` writes them exactly like consented
  reports (HMAC, masked form, week, category, trend observation), flagged demo so they count
  only in demo mode. The senders table comes from these reports.
- The same script also seeds **484 simulated checks** for the public trends (week, band and category
  only; no text, no indicators), demo-flagged and idempotent, so the 12-week chart and category
  table are populated: mostly insufficient evidence and likely legitimate, with high risk rising
  from 6 to about 15 checks a week. They have exactly the fields a real check records (every
  `/analyze` adds one anonymous week/band/category row), so the demo behaves like the real app;
  checks you run during the demo are added too. Two chart cells are deliberately
  below five (likely legitimate in the oldest week, high risk in the second week) to show the
  `<5` rule; the smaller categories (training/kit fee, fake government scheme, sender spoofing)
  also stay below five in most weeks. Every week in which a listed sender was last reported has
  a visible high-risk bar.
- `scam_shared_upi_corvane.txt` / `.pdf` shares the seeded UPI sender. Hand-derived band:
  payment +65, contact domain NXDOMAIN +30, no registration number +20, UPI reported by 3–9
  job seekers +25 = 140, capped at 100: High risk.
- The six PDFs are generated from the `.txt` files by `scripts/make_demo_pdfs.py` (reportlab, A4)
  as offer-letter layouts (company header, identifiers, date, subject, body, signature block) with
  a real text layer, so the demo exercises the PDF upload path without OCR. Tests check each PDF
  scores exactly like its `.txt`.
