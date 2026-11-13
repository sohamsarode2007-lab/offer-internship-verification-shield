# Antigravity Build Prompt — Offer & Internship Verification Shield

Copy everything below into Antigravity as the project instruction.

---

## CRITICAL INSTRUCTION — READ FIRST

**Do not write mock code, stub functions, placeholder implementations, or TODO-marked incomplete logic anywhere in this project.** Every function must be a real, working implementation the first time it is written. Specifically:

- Do NOT write functions that return hardcoded/fake data "for now."
- Do NOT write `# TODO: wire this up later` and return `None` or a placeholder dict instead.
- Do NOT simulate an external API call with a fake response — actually call the real API, with real error handling for when it fails, times out, or the key is missing.
- If a required external API needs a key that isn't available yet, the code must still be a complete, real implementation that reads the key from environment configuration and makes a real HTTP call — it must fail loudly and clearly (a real exception with a clear message) if the key is missing, not silently return fake success data.
- If something genuinely cannot be implemented without a decision from me, stop and ask me instead of writing a stub to fill the gap.
- Every verification module must contain real logic that actually performs the check it claims to perform, not a simplified version that only handles the happy path.

If at any point you are about to write a function that doesn't fully do what its name and docstring claim, stop and tell me instead of writing it anyway.

**A separate "Verified API Reference" section is included near the end of this document.** Consult it before writing any module that calls an external API — the specific vendor, endpoint pattern, and free-tier limit for each has already been researched and decided. Do not substitute a different vendor than what's listed there without asking me first.

---

## Project Summary

Offer & Internship Verification Shield is a web platform that lets a student upload a job/internship offer (PDF, screenshot, or pasted text) and receive a structured, explainable risk assessment. It differs from existing keyword-scanning tools by verifying **structural, factual reality** — real mail server infrastructure, real domain age, real government registry status, and correlation between the sender's domain and the legal entity claimed — rather than judging the tone or wording of the message. The LLM is used **only** for structured fact extraction from raw text; it never produces the final verdict. All scoring is deterministic and explainable.

---

## Full Architecture

```
[Client: Web UI]
      │  (upload PDF/image or paste text)
      ▼
[API Layer: FastAPI, /api/v1/scan]
  └─ Since the concurrent verification modules take several seconds combined, stream
       live progress to the client (Server-Sent Events, or polling as a simpler
       alternative) with real status updates as each module actually completes (e.g.,
       "Checking mail infrastructure..." → "Searching digital footprint...") — do not
       fake the progress sequence with a timer; it must reflect real module
       completion state.
      │
      ▼
[Ingestion]
  ├─ File uploads processed entirely in memory (`io.BytesIO`) — the raw file must
       NEVER be written to local disk or cloud storage at any point, not even
       temporarily, to strictly maintain the privacy design
  ├─ Image deskew/orientation correction (OpenCV: grayscale → Otsu threshold → deskew)
  ├─ OCR text extraction (PaddleOCR), or direct text-layer extraction for PDFs with a
  │    real text layer (check before falling back to OCR)
  ├─ Character-normalization pass on extracted text (correct common OCR digit/letter
  │    confusion — 0/O, 1/I/l — specifically before regex parsing of GSTIN/UPI/account
  │    numbers)
  ├─ WhatsApp/Telegram handle extraction: regex-extract `wa.me/<number>`,
  │    `t.me/<handle>`, and any bare phone/contact handles from the document text —
  │    feed these into the Digital Footprint Corroboration module as additional
  │    query material, since a scam operating purely through chat apps may have no
  │    domain at all but will usually have one of these
  ├─ Document hashing: SHA-256 (exact match) AND SimHash (near-duplicate match)
  └─ Duplicate check against stored hashes (Postgres as source of truth, Redis as a
       fast-path cache in front of it — NOT Redis alone, since Redis TTL expiry must
       not silently break duplicate detection)
      │
      ▼
[PII Redaction — runs BEFORE any text leaves this pipeline stage]
  └─ Presidio (or equivalent) masks: person names, phone numbers, addresses,
       Aadhaar-shaped numbers, PAN-shaped numbers
  └─ Company-facing information (company name, domain, GSTIN, payment details) is
       explicitly preserved, not redacted
      │
      ▼
[LLM Structured Extraction — Gemini Flash, JSON-mode/schema-enforced]
  └─ Input: redacted text only, never unredacted text
  └─ Output: validated against a strict Pydantic schema (company_name, sender_email,
       sender_domain, claimed_institution, gstin, cin, llpin, udyam_number,
       ngo_darpan_id, offer_role, stipend_amount, payment_demands[], upi_vpas[],
       urgency_phrases[], monetary_values[], extraction_confidence)
  └─ Real retry logic with exponential backoff on API failure — must actually retry
       against the real API, not simulate retries
      │
      ▼
[Completeness Assessment]
  └─ For each verification module, determine whether required input fields are present
  └─ Produces a CompletenessReport: total modules, evaluated, not_applicable, missing
       fields, completeness percentage
      │
      ▼
[Verification Modules — run concurrently via asyncio, each independent]
  │
  ├─ Module: DNS & Mail Infrastructure
  │    Real DNS queries (dnspython/dns.asyncresolver) for MX records, SPF TXT record,
  │    DMARC TXT record (_dmarc.<domain>). No external API needed — DNS queries are
  │    native and free. Cache results in Redis with TTL. Returns NOT_APPLICABLE if no
  │    sender domain was extracted.
  │
  ├─ Module: Domain Age
  │    Primary: RDAP (Registration Data Access Protocol) lookup — free, keyless,
  │    standardized successor to WHOIS (see Verified API Reference). Fallback only if
  │    RDAP returns no data for a given registry: python-whois, with an explicit
  │    3-second timeout (circuit breaker) — a slow registrar response must not block
  │    the other concurrent asyncio verification tasks. Compute age in days against a
  │    configurable threshold. Cache in Redis with TTL. Handle lookup failure or
  │    timeout (both RDAP and fallback) as a real FAIL with reduced confidence, not a
  │    crash.
  │
  ├─ Module: Institutional Affiliation Matcher
  │    Maintains a real, populated list of known Indian institution → official domain
  │    mappings (IITs, IIMs, NITs, major universities — build this list with real,
  │    verified domains, not placeholders). Exact match AND fuzzy/edit-distance match
  │    (rapidfuzz) to catch typosquatted lookalike domains. Returns NOT_APPLICABLE if
  │    no institutional claim was extracted.
  │
  ├─ Module: Government Entity Verification Cascade
  │    Step 1 — GSTIN: validate the Modulus-36 checksum locally (real implementation
  │      of the actual algorithm, not a placeholder). If the checksum FAILS, return a
  │      real FAIL immediately WITHOUT calling the external GSTIN API — this is a
  │      deliberate short-circuit to conserve the limited free-tier API quota, not a
  │      shortcut on correctness, since a locally-invalid checksum is already
  │      conclusive. Only call the external API when the checksum passes.
  │    Step 2 — CIN/LLPIN: if no GSTIN, or GSTIN verification fails/unavailable, call
  │      the MCA data source specified in the Verified API Reference section.
  │    Step 3 — Udyam/NGO Darpan: no free automated API was found for these during
  │      research. Do NOT integrate a paid enterprise KYB API for this tier without
  │      asking me first. Instead, implement this tier as a manual-assist fallback —
  │      if a Udyam number or NGO Darpan ID is present in the extracted facts, surface
  │      a pre-filled link to the official government portal for the student to
  │      confirm themselves, rather than an automated pass/fail. This is a deliberate
  │      design choice, not an incomplete implementation.
  │    Step 4: if none of GSTIN/CIN/LLPIN are present or verifiable at all, return
  │      NOT_APPLICABLE (explicitly NOT a fraud signal on its own) and let the scoring
  │      engine rely more heavily on the other modules.
  │    Step 5 — Domain-to-Entity Binding: whichever tier returns a verified legal name,
  │      fuzzy-match it against (a) the company name claimed in the offer AND (b)
  │      cross-check that the sender's email domain plausibly correlates with that
  │      legal entity (not just the company name text) — this specifically catches a
  │      real company's valid registration number being copy-pasted onto a forged
  │      offer sent from an unrelated domain. Flag distinctly as
  │      "Domain Impersonation Mismatch" when this specific pattern is detected,
  │      separately from a generic name mismatch. The report's human-readable reason
  │      for this specific flag must explicitly explain the pattern in plain language
  │      (e.g., "This offer includes a valid, active GSTIN registered to a real
  │      company, but the message was sent from an email address unrelated to that
  │      company — a common tactic where a scammer copies real registration details
  │      onto a forged offer") rather than a generic mismatch message, since this is
  │      the system's strongest and most explainable fraud signal.
  │
  ├─ Module: Payment & Urgency Pattern Scanner
  │    Systematic regex-based extraction of monetary amounts, UPI VPA patterns,
  │    payment-demand phrases, and urgency phrases (build real, comprehensive regex
  │    patterns, not a token example list). Detects co-location of a payment demand
  │    and urgency language within the same or adjacent sentences and weights this
  │    combination higher. Include a TF-IDF-based supplementary scoring layer trained
  │    on our own collected scam-sample dataset (ask me for the dataset file/location
  │    if not yet provided — do not substitute a public English-language dataset like
  │    EMSCAD/Kaggle fake_job_postings as a stand-in).
  │
  └─ Module: Digital Footprint Corroboration
       Calls the Tavily API (see Verified API Reference) with THREE separate,
       deliberately different queries per scan — not a multi-agent framework, plain
       sequential/concurrent function calls with different parameters each:
         1. General existence — query: "<company name>", include_answer=true (use
              Tavily's own synthesized answer as a free secondary signal)
         2. Negative-signal — query: "<company name> scam OR fraud OR complaint",
              search_depth="advanced", topic="news" (deeper crawl, biased toward
              journalism/reporting over forum noise — this is the highest-value query)
         3. Professional-presence — query: "<company name> careers OR jobs",
              include_domains=["linkedin.com","glassdoor.com","ambitionbox.com",
              "naukri.com"] (restricts to platforms that actually matter, not a
              generic web search)
       If a WhatsApp (`wa.me`) or Telegram (`t.me`) handle was extracted during
       ingestion, include it as additional query material — for entities with no
       domain at all, this may be the only independently-checkable identifier
       available.
       Combine the three results with explicit rule logic, not free-form LLM
       reasoning: zero hits across all three = weak/no footprint (real signal,
       feeds risk score up); hits in query 2 specifically = explicit negative
       evidence (strong signal, feeds risk score up further); hits in queries 1/3
       with nothing in query 2 = plausible legitimate entity, especially a young one
       (feeds the "insufficient evidence — verify manually" bucket rather than
       "risky"). Do NOT use an LLM to freely synthesize a verdict across the three
       result sets — the combination logic must be deterministic and explainable,
       consistent with every other module in this system.
       Note for cost planning: query 2's advanced search costs 2 Tavily credits vs.
       1 for the others, so each scan costs ~4 credits — roughly 250 scans/month on
       Tavily's free 1,000-credit tier.
      │
      ▼
[Risk Scoring Engine]
  └─ Primary path: logistic regression model trained on our own collected, labeled
       benchmark dataset (real scam and real legitimate offer samples — ask me for
       this dataset; do not generate synthetic/random training data as a substitute)
  └─ NOT_APPLICABLE results from any module must be correctly excluded from the
       feature vector AND the score denominator — verify this is actually implemented
       and write a test that would fail if it weren't
  └─ Fallback path: if no trained model is available, use a transparent weighted rule
       system (hardcoded, documented point values) — this fallback must be fully
       functional on its own, not a stub, since it's a legitimate part of the design
  └─ Explicit three-outcome design for entity verification specifically: PASS, FAIL,
       or "insufficient evidence — verify manually" (distinct from a generic
       NOT_APPLICABLE) when registry checks are absent but no other red flags are
       present and at least one digital-footprint trace was found
      │
      ▼
[Report Generation]
  └─ Final risk score (0-100) and categorical level (LOW/MEDIUM/HIGH/CRITICAL)
  └─ Per-module breakdown: status, confidence, human-readable reason, evidence payload
  └─ Completeness report with explicit missing-field callouts
  └─ Actionable recommendations, deduplicated
  └─ Duplicate-offer flag, referencing the original scan_id if a prior match was found
      │
      ▼
[Persistence]
  └─ PostgreSQL: only redacted, company-facing data — no raw uploaded file, no student
       PII — stored permanently, indexed by SHA-256 and SimHash for duplicate lookups
  └─ Redis: fast-path cache in front of Postgres for duplicate lookups, plus TTL cache
       for WHOIS/RDAP/DNS/registry lookups — must gracefully degrade (never crash the
       app) if Redis is unreachable
      │
      ▼
[Client: Displayed Report]
```

---

## Explicit Build Requirements

1. **Every verifier module listed above must be a complete, real implementation** including real external API calls, real error handling for timeouts/failures/missing credentials, and real caching — not a version that "would work once we add the API key."
2. **Configuration must be environment-driven** (Pydantic Settings reading from `.env`), and any required API key that is missing must cause a clear, real startup or request-time error — never a silent fallback to fake data.
3. **Write real tests** for each verifier module, including a test that specifically asserts NOT_APPLICABLE modules are excluded from the scoring calculation, and a test for the domain-to-entity binding mismatch detection.
4. **The external API vendors for GSTIN, CIN/LLPIN, domain age, and digital footprint corroboration are already decided — see the Verified API Reference section.** Do not substitute a different vendor for these four without asking me first. Udyam/NGO Darpan remains an open decision (manual-assist only, per the architecture above) — do not integrate a paid API for this tier without asking.
5. **If the TF-IDF training dataset or the logistic regression benchmark dataset isn't available in the project yet**, stop and ask me for it rather than generating synthetic placeholder data to make the code "run."
6. Use FastAPI's `lifespan` handler to pre-load heavy models (OCR engine, PII redaction analyzer, fuzzy-match lookup tables) once at startup, not per-request.
7. Duplicate detection must actually short-circuit the pipeline for a confirmed exact-hash match (return the prior stored report) rather than detecting a duplicate and still running the full pipeline anyway.
8. Rate limiting must key by client IP address when no API key is configured (the current codebase has a real bug here — all unauthenticated users currently share a single "anonymous" bucket, meaning one active user can lock out every other user; this must be fixed, not preserved). Implement via Redis, and this must protect the third-party API quotas (KnowYourGST, Tavily, etc.) specifically, not just the FastAPI endpoint generally.
9. The Completeness Report UI must be genuinely interactive, not read-only — when a scan returns missing fields, render actual editable input fields in the dashboard so the student can supply the missing value (e.g., a GSTIN they know but that wasn't extracted) and trigger a real partial re-scan of only the affected modules, without re-uploading the whole document. This is a real, functional feature, not a static display of what's missing.

---

## Tech Stack (do not substitute without asking)

Backend: Python, FastAPI · Database: PostgreSQL via SQLAlchemy (async) + Alembic migrations · Cache: Redis · OCR: PaddleOCR · Image processing: OpenCV · Fuzzy matching: rapidfuzz · PII redaction: Presidio · LLM: Gemini Flash (structured JSON mode) · DNS: dnspython · Domain age: RDAP (primary), python-whois (fallback only) · ML: scikit-learn (logistic regression) · Frontend: HTML/CSS/JavaScript (or React if already scaffolded) · Testing: pytest · Containerization: Docker + docker-compose

---

## Verified API Reference (researched and confirmed — August 2026)

This section lists the specific external API vendor for each module where one is needed. These are the result of dedicated research into free-tier availability and are the confirmed choices — treat this as authoritative, not as suggestions to re-evaluate.

| Module | Vendor | Free Tier | Implementation Notes |
|---|---|---|---|
| DNS / Mail Infrastructure | None — native `dnspython` | Unlimited, free forever | No third-party API involved at all |
| Domain Age | RDAP (standard protocol, no single "vendor" — query the relevant registry's RDAP server) | Free, no key required | Prefer over WHOIS; `python-whois` is fallback only, for registries with incomplete RDAP data |
| CIN / LLPIN (MCA) | Apify's "MCA India Company Registry" actor, built on data.gov.in's public "RoC-wise Company Master Data" (~3.67M companies) | Free — a shared rate-limited key works with no signup; use your own free `data.gov.in` API key to remove rate limiting entirely | Genuinely free, not freemium; confirmed no charge even on a failed/empty run |
| GSTIN | KnowYourGST (primary), AppyFlow (backup) | 50 free API calls each on signup, no payment info required | Both return legal name + active status needed for the name-match check; have the backup account ready before a live demo in case the primary account's quota runs low |
| Udyam / NGO Darpan | None — no free automated API was found during research | N/A | Implemented as a manual-assist link to the official government portal, per the architecture section above — do not add a paid enterprise KYB provider for this tier without asking first |
| Digital Footprint Corroboration | Tavily | 1,000 free credits/month, no credit card required | Confirmed choice. Google Custom Search JSON API was considered and rejected — it is closed to new signups and is being shut down entirely on 2027-01-01. Vertex AI Search/Grounding was also considered and rejected — no free tier as of Aug 2026, fragmented per-SKU pricing ($1.50-$6/1k queries plus separate grounding fees), and significant GCP setup overhead. Use THREE separate Tavily queries per scan with different parameters (general existence, advanced news-biased negative-signal search, domain-restricted professional-presence search) combined via deterministic rule logic — see the Digital Footprint Corroboration module in the architecture section for the exact query specs. Do not use LangGraph or any multi-agent framework for this — plain sequential API calls with rule-based combination only. ~4 credits/scan, ~250 scans/month on the free tier |
| LLM Structured Extraction | Google Gemini (Flash) | Free tier | Already in use in the current codebase |
| OCR | PaddleOCR | Free, open-source, runs locally | No API/key needed |
| PII Redaction | Presidio | Free, open-source, runs locally | No API/key needed |

---

## Project Structure (exact layout — create this, do not improvise a different one)

```
offer-shield/
├── app/
│   ├── main.py
│   ├── core/
│   │   ├── config.py          # Pydantic Settings, reads .env
│   │   ├── security.py        # APIKeyMiddleware, RateLimitMiddleware (IP-keyed)
│   │   ├── logging.py         # structlog setup
│   │   └── exceptions.py      # ShieldBaseError hierarchy + handler
│   ├── db/
│   │   ├── base.py            # SQLAlchemy declarative Base
│   │   └── session.py         # async engine, session factory, init_db/close_db
│   ├── models/
│   │   └── scan.py            # ScanRecord ORM model
│   ├── schemas/
│   │   ├── enums.py           # VerificationStatus, RiskLevel, InputFormat
│   │   ├── extracted.py       # ExtractedFacts
│   │   ├── verification.py    # ModuleResult + per-module *Detail schemas
│   │   ├── report.py          # CompletenessReport, ScoreBreakdown, FinalReport
│   │   └── request.py         # ScanRequest, ScanMetadata
│   ├── cache/
│   │   └── redis_client.py    # connection pool, cache_get/set/exists, key builders
│   ├── services/
│   │   ├── ingestion.py       # deskew, OCR, hashing, dedup check, PII redaction
│   │   ├── extraction.py      # Gemini structured extraction, completeness assessment
│   │   ├── scoring.py         # logistic regression + weighted fallback
│   │   └── orchestrator.py    # runs the full pipeline end to end
│   ├── verifiers/
│   │   ├── base.py            # BaseVerifier ABC, module_name, verify(), _not_applicable()
│   │   ├── dns_verifier.py
│   │   ├── domain_age.py
│   │   ├── institution_matcher.py
│   │   ├── legal_entity.py    # GSTIN/CIN/LLPIN cascade + domain-to-entity binding
│   │   ├── payment_urgency.py
│   │   └── digital_footprint.py   # Tavily 3-query module
│   └── routes/
│       ├── health.py
│       ├── scan.py            # POST /api/v1/scan, GET /api/v1/scan/stream (SSE)
│       └── report.py          # GET /api/v1/report/{scan_id}
├── ml/
│   └── train.py                # trains scoring.py's model from the real labeled dataset
├── data/
│   └── institutions.json       # real institution → domain mappings, loaded at startup
├── alembic/
│   ├── env.py
│   └── versions/
├── static/                     # frontend: index.html, style.css, app.js (or a built SPA)
├── tests/
│   ├── conftest.py
│   ├── test_ingestion.py
│   ├── test_verifiers.py
│   ├── test_scoring.py
│   ├── test_scan_route.py
│   └── test_schemas.py
├── Dockerfile
├── docker-compose.yml
├── alembic.ini
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
├── .env.example
└── .gitignore
```

Do not invent a different module boundary than this (e.g., do not merge `orchestrator.py` logic into `main.py`, do not put verifier logic inside route handlers). Each verifier stays a standalone class implementing `BaseVerifier` so it can be tested in isolation.

---

## Complete Schema Definitions (exact fields — implement these, do not approximate)

**`ExtractedFacts`** (Pydantic model, also the Gemini JSON-mode response schema):
- `company_name: str | None`
- `sender_email: str | None`
- `sender_domain: str | None`
- `claimed_designation: str | None`
- `claimed_institution: str | None`
- `gstin: str | None` — pattern `^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$`
- `cin: str | None` — pattern `^[UL][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$`
- `llpin: str | None` — pattern `^[A-Z]{3}-[0-9]{4}$`
- `udyam_number: str | None`
- `ngo_darpan_id: str | None`
- `whatsapp_handle: str | None` — extracted `wa.me/<number>` if present
- `telegram_handle: str | None` — extracted `t.me/<handle>` if present
- `offer_role: str | None`
- `stipend_amount: str | None`
- `currency: str` — default `"INR"`
- `start_date: str | None`
- `duration: str | None`
- `payment_demands: list[str]` — default empty list
- `upi_vpas: list[str]` — default empty list
- `urgency_phrases: list[str]` — default empty list
- `monetary_values: list[str]` — default empty list
- `raw_text_redacted: str` — required, the full OCR output with PII masked
- `extraction_confidence: float` — required, range 0.0–1.0

**`ModuleResult`** (returned by every verifier):
- `module_name: str`
- `status: VerificationStatus` — one of `pass`, `fail`, `not_applicable`
- `confidence: float` — range 0.0–1.0
- `reason: str` — required, human-readable
- `evidence: dict` — default empty dict, holds the module-specific detail schema serialized
- `suggestions: list[str]` — default empty list

**`CompletenessReport`**:
- `total_modules: int`
- `modules_evaluated: int`
- `modules_not_applicable: int`
- `missing_fields: list[str]`
- `completeness_pct: float` — range 0.0–100.0

**`FinalReport`** (top-level API response):
- `scan_id: str` (UUID v4)
- `timestamp: datetime`
- `risk_level: RiskLevel`
- `risk_score: float` — range 0.0–100.0
- `extracted_facts: ExtractedFacts`
- `module_results: list[ModuleResult]`
- `score_breakdown: list[ScoreBreakdown]`
- `completeness: CompletenessReport`
- `summary: str`
- `recommendations: list[str]`
- `is_duplicate: bool`
- `duplicate_of_scan_id: str | None`

**`ScanRecord`** (Postgres ORM model — redacted, company-facing data only, never raw file or student PII):
- `id: UUID` (primary key)
- `document_hash_sha256: str(64)`, indexed
- `document_hash_simhash: str(32)`, indexed
- `is_duplicate: bool`
- `duplicate_of_id: UUID | None`
- `extracted_facts: JSON`
- `module_results: JSON`
- `risk_score: float`
- `risk_level: str(20)`
- `completeness_pct: float`
- `summary: text`
- `created_at: datetime(timezone=True)`, indexed

---

## Scoring Thresholds & Fallback Weights (exact values — implement these, do not choose your own)

**Risk level bands** (applied to the final 0–100 score, regardless of which scoring path produced it):
- `LOW`: score < 25
- `MEDIUM`: 25 ≤ score < 50
- `HIGH`: 50 ≤ score < 75
- `CRITICAL`: score ≥ 75

**Weighted rule-engine fallback** (used only when no trained logistic regression model is available — must sum to 100 across the six modules):
- `dns_verification`: 12
- `domain_age`: 12
- `institution_match`: 12
- `legal_entity`: 18 (this includes the domain-to-entity binding check — a Domain Impersonation Mismatch on this module should push its contribution to the maximum of this weight's range, not a partial value, since it is the strongest available signal)
- `digital_footprint`: 16
- `payment_urgency`: 30 (highest weight — payment/urgency co-location is the single most financially dangerous signal)

A module with status `not_applicable` contributes 0 to both the numerator and is excluded from the denominator — recompute the effective total weight from only the modules that actually ran, then normalize to 0–100. Do not divide by a fixed 100 if one or more modules were `not_applicable`.

**Three-outcome entity verification override**: even after the weighted/ML score is computed, if `legal_entity` returned `not_applicable` (no GSTIN/CIN/LLPIN at all) AND `digital_footprint` found at least one positive trace (queries 1 or 3) AND `payment_urgency` returned `pass` (no payment/urgency red flags) AND `dns_verification` did not fail outright, cap the resulting risk level at `MEDIUM` even if the raw weighted score would otherwise round up to `HIGH`, and label it explicitly in the summary as "insufficient evidence — verify manually" rather than a generic risk description. This is the concrete implementation of the "young legitimate startup" fix — do not skip this override step.

---

## API Endpoint Contracts

**`POST /api/v1/scan`**
- Request: `multipart/form-data` with `input_format` (`pdf` | `image` | `text`), and either `raw_text` (form field, required if `input_format=text`) or `file` (file upload, required otherwise)
- Response: `201 Created`, body = `FinalReport` (see schema above)
- Error responses: `400` (missing/invalid input), `415` (unsupported file type), `413` (file too large), `422` (OCR/extraction failure), `502` (LLM or external API failure), `504` (verification module timeout)

**`GET /api/v1/scan/stream`**
- Server-Sent Events endpoint. Same input as `/scan` (accept as query params or an initial POST that returns a stream token — pick one approach and document it in the code, but implement it for real, not as a fake timer-driven progress bar)
- Each event: `data: {"stage": "<module_name or pipeline stage>", "status": "started"|"completed", "message": "<human-readable>"}\n\n`
- Final event carries the complete `FinalReport` with `"stage": "done"`

**`GET /api/v1/report/{scan_id}`**
- Response: `200 OK` with the stored `FinalReport`, or `404` if not found, or `400` if `scan_id` is not a valid UUID

**`GET /health`**
- Returns `{"status": "ok"|"degraded", "database": "connected"|"disconnected", "redis": "connected"|"disconnected"}`. Must return HTTP `503` (not `200`) when `status` is `"degraded"` — this was a known bug in an earlier version of this codebase (health check always returned 200 regardless of DB state) and must not be repeated.

---

## Environment Variables (`.env.example` — create this exact file)

```
APP_NAME=Offer Verification Shield
APP_ENV=development
DEBUG=false
LOG_LEVEL=INFO
API_V1_PREFIX=/api/v1

API_KEY_HEADER=X-API-Key
API_KEYS=[]
CORS_ORIGINS=["http://localhost:8000"]

DATABASE_URL=postgresql+asyncpg://shield:shield_pass@localhost:5432/offer_shield
DATABASE_POOL_SIZE=10
DATABASE_MAX_OVERFLOW=20

REDIS_URL=redis://localhost:6379/0
REDIS_TTL_WHOIS=86400
REDIS_TTL_DNS=86400
REDIS_TTL_DOCUMENT=604800

GOOGLE_API_KEY=
GEMINI_MODEL=gemini-flash-latest
GEMINI_TEMPERATURE=0.1
GEMINI_MAX_RETRIES=3

OCR_LANGUAGE=en
OCR_USE_GPU=false

DOMAIN_AGE_MIN_DAYS=90
WHOIS_TIMEOUT_SECONDS=3
TYPOSQUAT_MAX_EDIT_DISTANCE=2
INSTITUTION_FUZZY_THRESHOLD=85
LEGAL_NAME_FUZZY_THRESHOLD=80

KNOWYOURGST_API_KEY=
APPYFLOW_API_KEY=
DATA_GOV_IN_API_KEY=
TAVILY_API_KEY=

MAX_UPLOAD_SIZE_MB=10
ALLOWED_MIME_TYPES=["application/pdf","image/png","image/jpeg","image/webp","text/plain"]

RATE_LIMIT_PER_MINUTE=10
```

Every key above with an empty value must be treated as "not yet provided" — reading it and finding it empty at the moment a module actually needs it should raise a clear, real exception (e.g., `ExternalAPIError("TAVILY_API_KEY is not configured")`), not silently skip the check or return fake data. Ask me for the actual key value when you reach the point of needing it, per the phased build order below.

---

## Error Handling & Concurrency Pattern

- Verification modules run via `asyncio.gather(*, return_exceptions=True)`. If any individual verifier raises an exception, catch it at the orchestrator level and convert it into a `ModuleResult` with `status=not_applicable`, `confidence=0.0`, and `reason=f"Module error: {exception}"` — the whole scan must never crash because one module failed; the other modules' results must still be returned.
- Every verifier's own internal external-API calls must have explicit timeouts (see the RDAP/WHOIS 3-second circuit breaker as the pattern to follow for every other external call too — DNS, GSTIN/CIN/Tavily lookups all need their own explicit timeout, not an indefinite wait).
- Redis failures must never crash the app — every cache read/write is wrapped so a Redis outage degrades to "no caching" silently at the infrastructure level, while still being logged.
- Postgres failures during the final persistence step should not prevent the `FinalReport` from being returned to the client — log the failure clearly, but the student should still see their scan result even if the write-behind to the database fails.

---

## Testing Requirements (exact test list — write these, not a different arbitrary set)

- `test_gstin_checksum_valid` / `test_gstin_checksum_invalid` — Modulus-36 algorithm correctness
- `test_legal_entity_not_applicable_when_no_identifiers` — confirms Step 4 of the cascade
- `test_domain_entity_binding_mismatch_detected` — a real company name/GSTIN paired with an unrelated domain must produce a `Domain Impersonation Mismatch`, not a generic fail
- `test_not_applicable_excluded_from_score` — construct a set of module results including at least one `not_applicable`, assert it does not affect the numeric score and is excluded from the denominator (this specifically guards against the exact bug found in an earlier version of this codebase, where `NOT_APPLICABLE` results were computed into the ML feature vector as if they were `PASS`)
- `test_insufficient_evidence_override` — confirms the three-outcome cap described in the Scoring Thresholds section actually triggers under the specified conditions
- `test_duplicate_short_circuit` — submitting the same document hash twice must not re-run the full pipeline the second time
- `test_payment_urgency_colocation` — a payment demand and urgency phrase in the same sentence must be detected and weighted higher than either alone
- `test_institution_typosquat_detected` — a domain that's a near-miss of a real institution's domain must be flagged, not silently passed
- `test_health_check_returns_503_when_degraded` — guards against the known bug described in the API contract section above
- `test_rate_limit_keyed_by_ip` — two different IPs without an API key must not share a rate-limit bucket (guards against the known bug in an earlier version of this codebase)

---

## What to do if you're unsure

If any instruction above is ambiguous, or you're about to implement something with a guess instead of a confirmed decision (a vendor not listed in the Verified API Reference, a dataset source, threshold values), **stop and ask me a specific question** rather than proceeding with an assumption or a placeholder. A clarifying question is always preferable to code that looks finished but isn't real.


Read the attached antigravity_build_prompt.md fully before writing any code.

Before starting implementation, confirm back to me:
1. Your understanding of the no-mock-code rule and what you'll do if you hit a
   genuine gap (API key not yet provided, dataset not yet available).
2. The build order you plan to follow.

Then build in this order, stopping between phases for me to review before continuing:

Phase 1 — Foundation (no external API keys needed yet):
  Project scaffolding, Docker/docker-compose, config/settings, database models +
  Alembic migration, Redis client, FastAPI app with lifespan handler, exception
  hierarchy, logging.

Phase 2 — Ingestion pipeline:
  BytesIO in-memory file handling, OpenCV deskew, PaddleOCR + PDF text-layer
  detection, character normalization, WhatsApp/Telegram handle extraction,
  SHA-256 + SimHash hashing, duplicate short-circuit logic, Presidio PII redaction.

Phase 3 — Extraction:
  Gemini structured extraction with the Pydantic schema, completeness assessment.

Phase 4 — Verification modules (can be built in any order, but keep them independent):
  DNS/mail infrastructure, domain age (RDAP + WHOIS fallback with circuit breaker),
  institutional matcher, government entity cascade with domain-to-entity binding,
  payment/urgency scanner, digital footprint (Tavily, 3-query).
  I will provide API keys as you reach each one that needs a real key — ask me by
  name for the specific key when you get there rather than stubbing around it.

Phase 5 — Scoring:
  Weighted rule-engine fallback first (fully functional on its own). Logistic
  regression path only once I've provided the labeled dataset — ask me for it by
  name when you reach this phase if I haven't already provided it.

Phase 6 — Orchestration, API routes, SSE progress streaming, rate limiting fix.

Phase 7 — Frontend: upload flow, interactive completeness dashboard, results display.

Start with Phase 1. Show me the scaffolding before moving to Phase 2.