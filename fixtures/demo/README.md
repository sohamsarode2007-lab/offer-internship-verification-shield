# Demo documents (synthetic)

Every document and data file in this folder is **synthetic**. Every company, scheme, person,
registration number, phone number, account number and domain in them is fictional.

| File | Pattern it demonstrates |
|------|-------------------------|
| `legit_emberlake.txt` / `.pdf` | Established private company: valid-structure GSTIN + CIN, company domain, explicit no-fee statement |
| `legit_brightpath_young_startup.txt` / `.pdf` | Genuine-looking young startup with no GST registration (below threshold) |
| `scam_fake_govt_scheme_fee.txt` / `.pdf` | Fake government scheme demanding a "refundable" verification fee via bank/UPI, with urgency |
| `registry_name_match_quillmere.txt` | CIN matches an active company with the same name in the synthetic registry |
| `registry_struck_off_tarnwick.txt` | CIN belongs to a company whose registry status is Struck Off |
| `registry_cin_mismatch_halvorn.txt` | Offer claims one company but quotes the CIN of a different company |
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
- `scam_reports.csv` contains synthetic community-network examples with reserved `.example`
  domains. With `DEMO_MODE=1` and an environment-provided `INDICATOR_PEPPER`, run
  `python scripts/seed_demo_reports.py`. It uses the normal token/consent service path; rows are
  marked demo and ignored outside demo mode.
- The PDFs are generated from the `.txt` files by `scripts/make_demo_pdfs.py` (reportlab, A4,
  line breaks preserved) so the demo also exercises the PDF upload path.
