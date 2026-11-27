# Live checks (you run these; nothing here has been run against the real services)

The automated tests and the evaluation mock DNS, WHOIS and HTTP, and Tesseract OCR runs only in CI. So these items are
**untested against the real world** until you have done the list below. Tick each one and note the date; paste any
FAIL output back and it will be fixed.

## 1. One command for the outbound features

```
$env:DATA_GOV_IN_API_KEY = "..."      # optional; the check is skipped without it
$env:WEB_RISK_API_KEY    = "..."      # optional; the check is skipped without it
.\.venv\Scripts\python.exe -m scripts.live_checks --careers-domain <a domain you know has a careers page>
```

It sends only fixed test addresses, never offer text, and never prints a key. A SKIP means "not tested", not "passed".

| Check | PASS means | If it FAILs |
|---|---|---|
| data.gov.in host, key, field names | the host answers with the key and rows carry CIN, CompanyName, CompanyStatus | read the HTTP code it prints; a moved host can be set with `DATA_GOV_IN_BASE_URL` |
| data.gov.in `filters[CIN]` | looking up an existing CIN returns that company | the API may ignore the filter; the app already treats unrelated rows as "unavailable", but the live registry lookup then adds nothing |
| Web Risk: test page and harmless page | Google lists its test page and does not list example.com | 403 usually means the Web Risk API is not enabled for that key; if only the test page is unlisted, confirm Google's current test URL |
| Redirect and TLS | http to https redirect followed; expired and wrong-host certificates reported invalid | "stopped before a verdict" means your network blocked it; try another network |
| Private address refused | localhost is refused | any FAIL here is a security bug: stop and report |
| Careers page | a careers page is found on the domain you gave | many sites block automated requests; this one is expected to miss sometimes |

## 2. Things a script cannot check (do by hand, once)

- [ ] **Docker build and run.** `docker build -t shield .` then run it with the production variables from README
  (`ENVIRONMENT=production`, a 32+ character `INDICATOR_PEPPER`, explicit `ALLOWED_ORIGINS`, a Postgres `DATABASE_URL`,
  `FORWARDED_ALLOW_IPS`). The container must start; remove one variable and it must refuse to start with a clear message.
- [ ] **Content-Security-Policy in a real browser.** Open the deployed site with the browser console open, check a
  pasted offer, upload a file, open the report dialog and the How it works page. There must be no "Refused to ..." CSP
  errors. If there are, send the console text.
- [ ] **Rate limit and proxy on the real host.** From two different networks, send more requests than `RATE_LIMIT`
  allows. Each network should be limited separately (if everyone shares one limit, `FORWARDED_ALLOW_IPS` is wrong).
  Counters are per server process: with more than one worker, set `RATE_LIMIT_STORAGE_URI` to a shared store.
- [ ] **OCR on real images.** Upload a phone photo of a printed offer and a scanned PDF. The text must read sensibly.
  Tesseract only; `HEAVY_OCR` stays off.
- [ ] **Screenshot pass.** Look at the result page for a high-risk, a manual-review and a likely-legitimate offer on a
  phone-width window and a desktop window.

## 3. Still needs a person

- A small **independent test set**: offers collected by someone other than the rule author, kept out of rule writing.
  Until then the evaluation measures the rules against cases the author wrote, which flatters them.
- A **native-speaker review** of the Hindi and Hinglish scam and personal-data rules.
