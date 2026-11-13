# Demo documents (synthetic)

All three documents in this folder are **synthetic**. Every company, scheme, person,
registration number, phone number, account number and domain in them is fictional.

| File | Pattern it demonstrates |
|------|-------------------------|
| `legit_emberlake.txt` / `.pdf` | Established private company: valid-structure GSTIN + CIN, company domain, explicit no-fee statement |
| `legit_brightpath_young_startup.txt` / `.pdf` | Genuine-looking young startup with no GST registration (below threshold) |
| `scam_fake_govt_scheme_fee.txt` / `.pdf` | Fake government scheme demanding a "refundable" verification fee via bank/UPI, with urgency |

Notes:

- The Emberlake GSTIN `07AAFCE4321L1ZO` passes the official check-character test, but it is
  **not** a registered GSTIN. The system only checks structure; it never claims a registry match.
- Company domains use the reserved `.example` TLD, which **never resolves** in DNS. For a demo,
  run the backend with `DEMO_MODE=1` and
  `DEMO_FIXTURE_DOMAINS=emberlakeanalytics.example,brightpathedtech.example`.
  The domain check then returns `pass`, and its details start with
  `[DEMO FIXTURE — not a live DNS result]`, so the output always says it is a fixture.
- Without `DEMO_MODE`, the `.example` domains fail the MX check (NXDOMAIN), which is the correct
  live behaviour.
- The PDFs are generated from the `.txt` files by `scripts/make_demo_pdfs.py` (reportlab, A4,
  line breaks preserved) so the demo also exercises the PDF upload path.
