import { FormEvent, useEffect, useId, useMemo, useRef, useState } from 'react'
import { analyze, loadConfig, loadDashboard, loadSources, SENDERS_CSV_URL, submitDispute, submitReport, verifyDispute, WEEKLY_CSV_URL, withdrawReport } from './api/client'
import { buildInvestigationReport } from './investigationReport'
import { CONSENT_TEXT, CONSENT_VERSION, LINK_CONSENT_TEXT } from './consent'
import type { AnalyzeResponse, CheckResult, DisputeRequest, InstitutionDashboard, ReportableIndicator, RiskBand, ScamCategory, TopSender } from './api/types'
import styles from './App.module.css'

const labelByCheck: Record<string, string> = {
  sender_authentication: 'Who sent it', domain_verification: 'Email domain',
  gstin_verification: 'Company registration', payment_detection: 'Payment request',
  scam_text_patterns: 'Scam-chat wording', personal_data_request: 'Request for bank details or documents', community_reports: 'Reports from other job seekers',
}
const statusText: Record<CheckResult['status'], string> = {
  pass: 'Passed', fail: 'Failed', insufficient_information: 'Not enough information', not_applicable: 'Not applicable',
}
const statusGlyph: Record<CheckResult['status'], string> = { pass: '✓', fail: '✕', insufficient_information: '○', not_applicable: '—' }
const categoryLabels: Record<ScamCategory, string> = {
  registration_fee: 'Registration fee', security_deposit: 'Security deposit', training_or_kit_fee: 'Training or kit fee',
  fake_government_scheme: 'Fake government scheme', task_or_chat_scam: 'Task or chat scam', free_mailbox_impersonation: 'Free mailbox impersonation',
  lookalike_domain: 'Lookalike domain', sender_spoofing: 'Sender spoofing', no_red_flags: 'No red flags', other: 'Other',
}
const bandClass = (band?: string | null) => band === 'high risk' ? styles.highRisk : band === 'likely legitimate' ? styles.likely : styles.manual

function Header() {
  return <header className={styles.header}><a className={styles.brand} href="/">Offer shield</a><nav aria-label="Main navigation"><a href="/how-it-works">How it works</a><a href="/dashboard">Scam trends</a></nav></header>
}
function Footer() {
  return <footer className={styles.footer}><span>Check independently before you pay or share sensitive details.</span><nav aria-label="Support links"><a href="/withdraw">Withdraw a report</a><a href="/dispute">Dispute an indicator</a></nav></footer>
}
function Shell({ children }: { children: React.ReactNode }) { return <><Header/><main className={styles.main}>{children}</main><Footer/></> }

type Submitted = { text: string; file: File | File[] | null }

function Home({ onResult }: { onResult: (result: AnalyzeResponse, input: Submitted) => void }) {
  const [text, setText] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const file: File | File[] | null = files.length === 0 ? null : files.length === 1 ? files[0] : files
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [linkOffer, setLinkOffer] = useState(false)
  const [linkConsent, setLinkConsent] = useState(false)
  useEffect(() => { let live = true; loadConfig().then(c => { if (live) setLinkOffer(c.link_lookups) }); return () => { live = false } }, [])
  const fileInputId = useId()
  const [pickNote, setPickNote] = useState('')
  async function run(event: FormEvent) {
    event.preventDefault(); setError('')
    if (!text.trim() && !file) { setError('Paste offer text or choose a file to check.'); return }
    setBusy(true)
    try { onResult(await (linkOffer && linkConsent ? analyze(text, file, true) : analyze(text, file)), { text, file }); window.scrollTo({ top: 0, behavior: 'instant' }) }
    catch (err) { setError(err instanceof Error ? err.message : 'The request failed. Try again.') }
    finally { setBusy(false) }
  }
  return <section className={styles.home}>
    <div className={styles.homeIntro}><h1>Check an offer before you pay anything.</h1><p>We check payment requests, sender details and available company records.</p></div>
    <form onSubmit={run} className={styles.intake}>
      <div className={styles.intakeGrid}>
        <label className={styles.textWell}><span>Paste offer text</span><textarea value={text} onChange={e => setText(e.target.value)} disabled={busy} placeholder="Paste the message or offer letter here" rows={12}/></label>
        <div className={styles.uploadWell}><label htmlFor={fileInputId} className={styles.uploadLabel}>Choose up to 5 files (PDF, image or .txt), or one .eml</label><input id={fileInputId} type="file" multiple accept=".pdf,.png,.jpg,.jpeg,.bmp,.tiff,.eml,.txt" disabled={busy} onChange={e => { const picked = Array.from(e.target.files ?? []); setFiles(picked.slice(0, 5)); setPickNote(picked.length > 5 ? `Only the first 5 of ${picked.length} files were kept.` : picked.length > 1 && picked.some(f => f.name.toLowerCase().endsWith('.eml')) ? 'An .eml must be uploaded on its own. Choose either the .eml or the other files.' : '') }}/>
          <p className={styles.help}>Uploading the original email lets us read its sender-check results (SPF, DKIM, DMARC). Anyone can edit those lines in a file, so a failure counts against the offer but a pass is never counted as proof. Upload one .eml on its own; PDFs, images and .txt files can go together (up to 5).</p><p className={styles.help}>Gmail: open the message → ⋮ → “Download message”.</p>
          {pickNote && <p className={styles.help} role="status">{pickNote}</p>}{files.length > 0 && <p className={styles.selectedFile}>Selected: {files.map(f => f.name).join(', ')}</p>}
        </div>
      </div>
      {linkOffer && <label className={styles.consent}><input type="checkbox" checked={linkConsent} onChange={e => setLinkConsent(e.target.checked)} disabled={busy}/><span>{LINK_CONSENT_TEXT}</span></label>}
      <div className={styles.submitLine}><button type="submit" disabled={busy}>{busy ? 'Checking…' : 'Check offer'}</button><p>We don’t store your offer or your personal details. Only the result is kept.</p></div>
      {error && <p className={styles.error} role="alert">{error}</p>}
    </form>
  </section>
}

const sourceText: Record<string, string> = {
  dns_lookup: 'DNS lookup', offer_text: 'offer text', email_headers: 'email headers', community_reports: 'community reports',
  offer_text_and_local_registry_snapshot: 'offer text and local company snapshot', derived_check: 'derived check',
}
const affectsText: Record<string, string> = { score: 'affects the score', safety_floor: 'forces high risk', context: 'no score effect' }

function EvidenceLedger({ checks, meta = [] }: { checks: CheckResult[]; meta?: NonNullable<AnalyzeResponse['evidence_meta']> }) {
  return <section className={styles.ledgerSection}><h2>Evidence</h2><div className={styles.ledgerWrap}><table className={styles.ledger} aria-label="Evidence"><thead><tr><th scope="col">Check</th><th scope="col">Result</th></tr></thead><tbody>{checks.map((check, index) => {
    const details = check.details ?? ''
    const m = meta.find(item => item.check_name === check.check_name)
    return <tr className={styles.ledgerRow} key={`${check.check_name}-${index}`} style={{ '--row-index': index } as React.CSSProperties}>
      <th scope="row">{labelByCheck[check.check_name] ?? check.check_name.replaceAll('_', ' ')}</th>
      <td><span className={styles.status}><span aria-hidden="true">{statusGlyph[check.status]}</span> {statusText[check.status]}</span>{m && <span className={styles.sourceNote}>Source: {sourceText[m.source] ?? m.source} · {affectsText[m.affects] ?? m.affects} · confidence: {m.confidence === 'none' ? 'not enough to tell' : m.confidence}</span>}{details && <details className={styles.details}><summary>Details</summary><p>{details}</p></details>}</td>
    </tr>
  })}</tbody></table></div></section>
}

function downloadReport(result: AnalyzeResponse) {
  const url = URL.createObjectURL(new Blob([buildInvestigationReport(result)], { type: 'text/markdown' }))
  const link = document.createElement('a'); link.href = url; link.download = 'offer-check-report.md'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 10_000)   // revoking at once cancels the download in Safari and Firefox
}

function Complaint({ summary }: { summary: string }) {
  const [copyState, setCopyState] = useState<'' | 'copied' | 'failed'>('')
  const copy = async () => { try { await navigator.clipboard.writeText(summary); setCopyState('copied') } catch { setCopyState('failed') } }
  function download() {
    const url = URL.createObjectURL(new Blob([`# Report summary\n\n${summary}\n`], { type: 'text/markdown' }))
    const link = document.createElement('a'); link.href = url; link.download = 'report-summary.md'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 10_000)
  }
  return <section className={styles.complaint}><h2>Report it to the police</h2><p>{summary}</p><div className={styles.actions}><button type="button" className={styles.secondaryButton} onClick={copy}>{copyState === 'copied' ? 'Copied' : 'Copy summary'}</button><button type="button" className={styles.secondaryButton} onClick={download}>Download summary</button></div>{copyState === 'failed' && <p role="alert" className={styles.error}>Could not copy automatically. Select the summary text above and copy it yourself.</p>}</section>
}

function ReportDialog({ token, indicators, onClose }: { token: string; indicators: ReportableIndicator[]; onClose: () => void }) {
  const [selected, setSelected] = useState(() => new Set(indicators.map(i => i.id)))
  const [consented, setConsented] = useState(false)
  const [step, setStep] = useState(1)
  const [withdrawalCode, setWithdrawalCode] = useState('')
  const [copyState, setCopyState] = useState<'' | 'copied' | 'failed'>('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const dialogRef = useRef<HTMLDivElement>(null)
  const previousFocus = useRef<HTMLElement | null>(null)
  useEffect(() => {
    previousFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    dialogRef.current?.querySelector<HTMLElement>('button, input')?.focus()
    const keydown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') { onClose(); return }
      if (event.key !== 'Tab' || !dialogRef.current) return
      const items = [...dialogRef.current.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), a[href]')]
      const first = items[0], last = items[items.length - 1]
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
    }
    document.addEventListener('keydown', keydown)
    return () => { document.removeEventListener('keydown', keydown); previousFocus.current?.focus() }
  }, [onClose])
  const toggle = (id: string) => setSelected(old => { const next = new Set(old); next.has(id) ? next.delete(id) : next.add(id); return next })
  async function submit() {
    if (!consented) return
    setBusy(true); setError('')
    try { const response = await submitReport({ report_token: token, consent: true, consent_version: CONSENT_VERSION, selected_indicators: [...selected] }); setWithdrawalCode(response.withdrawal_code) }
    catch (err) { setError(err instanceof Error ? err.message : 'The report could not be submitted.') }
    finally { setBusy(false) }
  }
  async function copyCode() { try { await navigator.clipboard.writeText(withdrawalCode); setCopyState('copied') } catch { setCopyState('failed') } }
  return <div className={styles.modalBackdrop} onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}><div ref={dialogRef} className={styles.dialog} role="dialog" aria-modal="true" aria-labelledby="report-title" tabIndex={-1}>
    <button className={styles.closeButton} aria-label="Close report dialog" onClick={onClose}>Close</button>
    {!withdrawalCode ? step === 1 ? <><h2 id="report-title">Choose details to share</h2><p>Review the masked details extracted from this offer.</p>
      <fieldset className={styles.indicators}><legend>Payment and contact details</legend>{indicators.map(indicator => <label key={indicator.id}><input type="checkbox" checked={selected.has(indicator.id)} onChange={() => toggle(indicator.id)}/><span>{({ upi: 'Payment UPI ID', bank: 'Payment bank account', phone: 'Contact phone', email: 'Sender email', domain: 'Sender email domain' })[indicator.indicator_type]}</span><span className={styles.masked}>{indicator.masked}</span></label>)}{!indicators.length && <p>No payment or contact details were available to share. The wording fingerprint can still be shared with consent.</p>}</fieldset>
      <p className={styles.help}>Untick anything that’s yours or that you don’t want to share.</p>
      <button onClick={() => setStep(2)}>Continue</button>
    </> : <><h2 id="report-title">Review and consent</h2><p>Only the selected indicators and a redacted wording fingerprint will be shared.</p>
      <label className={styles.consent}><input type="checkbox" checked={consented} onChange={e => setConsented(e.target.checked)}/><span>{CONSENT_TEXT}</span></label>
      {error && <p className={styles.error} role="alert">{error}</p>}
      <div className={styles.actions}><button type="button" className={styles.secondaryButton} onClick={() => setStep(1)}>Back</button><button onClick={submit} disabled={!consented || busy}>{busy ? 'Sending…' : 'Report scam'}</button></div>
    </> : <><h2 id="report-title">Reported</h2><p>Future job seekers who receive the same details will be warned.</p><div className={styles.withdrawCode}><span>Withdrawal code</span><strong>{withdrawalCode}</strong></div><button className={styles.secondaryButton} onClick={copyCode}>{copyState === 'copied' ? 'Copied' : 'Copy code'}</button>{copyState === 'failed' && <p className={styles.error} role="alert">Could not copy automatically. Save the code above manually.</p>}<p className={styles.help}>Save this code. It’s the only way to withdraw this report, and we can’t show it again.</p><button className={styles.textButton} onClick={onClose}>Close</button></>}
  </div></div>
}

const verdictText: Record<string, { title: string; subline?: string }> = {
  'likely legitimate': { title: 'Likely legitimate' },
  'insufficient evidence, verify manually': { title: 'Insufficient evidence', subline: 'Verify manually before you proceed' },
  'high risk': { title: 'High risk' },
}
const REPORTABLE_BANDS = new Set(['high risk', 'insufficient evidence, verify manually'])

function WhyList({ result }: { result: AnalyzeResponse }) {
  const reasons = result.reasons ?? []
  if (reasons.length) {
    return <section className={styles.why}><h2>Why</h2><table className={styles.whyTable} aria-label="Why"><thead className={styles.visuallyHidden}><tr><th scope="col">Reason</th><th scope="col">Score impact</th></tr></thead><tbody>{reasons.map((r, i) => <tr key={i}><td>{r.text}</td><td className={styles.impact}>{r.impact ?? ''}</td></tr>)}</tbody></table></section>
  }
  return result.risk_factors?.length > 0 ? <section className={styles.why}><h2>Why</h2><ul>{result.risk_factors.map((factor, i) => <li key={i}>{factor}</li>)}</ul></section> : null
}

function AddEvidence({ result, input, onResult }: { result: AnalyzeResponse; input: Submitted; onResult: (result: AnalyzeResponse, input: Submitted) => void }) {
  const hints = result.evidence_hints ?? []
  const [extra, setExtra] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const fileId = useId()
  const fileRef = useRef<HTMLInputElement>(null)
  if (!hints.length) return null
  async function recheck(event: FormEvent) {
    event.preventDefault(); setError('')
    if (!extra.trim() && !file) { setError('Add some text or choose a file first.'); return }
    const next = { text: [input.text, extra.trim()].filter(Boolean).join('\n\n'), file: file ?? input.file }
    setBusy(true)
    try {
      const updated = await analyze(next.text, next.file)
      setExtra(''); setFile(null)
      if (fileRef.current) fileRef.current.value = ''
      onResult(updated, next)
      window.scrollTo({ top: 0, behavior: 'instant' })
    }
    catch (err) { setError(err instanceof Error ? err.message : 'The request failed. Try again.') }
    finally { setBusy(false) }
  }
  return <section className={styles.addEvidence}><h2>Make this check stronger</h2>
    <ul className={styles.hintCards}>{hints.map(h => <li key={h.id}><strong>{h.title}</strong><span>{h.why}</span><em>{h.how}</em></li>)}</ul>
    <form onSubmit={recheck}>
      <label className={styles.textWell}><span>More details to add</span><textarea value={extra} onChange={e => setExtra(e.target.value)} disabled={busy} rows={4} placeholder="Paste the sender's address, CIN or GSTIN, or anything else from the offer"/></label>
      <label htmlFor={fileId} className={styles.uploadLabel}>Add a file (original email, screenshot or QR code)</label>
      <input ref={fileRef} id={fileId} type="file" accept=".pdf,.png,.jpg,.jpeg,.bmp,.tiff,.eml,.txt" disabled={busy} onChange={e => setFile(e.target.files?.[0] ?? null)}/>
      <p className={styles.help}>Only one file is checked at a time; a new file replaces the earlier one. Nothing you add is stored.</p>
      <button type="submit" disabled={busy}>{busy ? 'Checking…' : 'Check again with this'}</button>
      {error && <p className={styles.error} role="alert">{error}</p>}
    </form></section>
}

function SafetyActions({ actions }: { actions: NonNullable<AnalyzeResponse['safety_actions']> }) {
  if (!actions.length) return null
  return <section className={styles.guidance} aria-label="Safety steps"><h2>Protect yourself now</h2>
    <ul className={styles.safetyCards}>{actions.map(a => <li key={a.id} className={a.urgent ? styles.urgentSafety : undefined}>
      <strong>{a.urgent ? 'Important: ' : ''}{a.title}</strong>
      <ul>{a.steps.map((step, i) => <li key={i}>{step}</li>)}</ul>
      {a.helpline && a.url && <span className={styles.actions}>
        <a href={`tel:${a.helpline}`}>Call {a.helpline}</a>
        <a href={a.url} target="_blank" rel="noopener noreferrer">National Cyber Crime Reporting Portal</a>
      </span>}
    </li>)}</ul></section>
}

function SelfChecks({ checks }: { checks: NonNullable<AnalyzeResponse['self_checks']> }) {
  const [copied, setCopied] = useState('')
  if (!checks.length) return null
  async function copy(id: string, value: string) {
    try { await navigator.clipboard.writeText(value); setCopied(id) } catch { setCopied('') }
  }
  return <section className={styles.addEvidence}><h2>Check it yourself</h2>
    <ul className={styles.hintCards}>{checks.map(c => <li key={c.id}>
      <strong>{c.title}</strong><span>{c.why}</span>
      <code>{c.number}</code>
      <ol>{c.steps.map((step, i) => <li key={i}>{step}</li>)}</ol>
      <em>{c.caution}</em>
      <span className={styles.actions}>
        <a href={c.url} target="_blank" rel="noopener noreferrer">Open the Udyam verification page</a>
        <button type="button" className={styles.secondaryButton} onClick={() => copy(c.id, c.number)}>{copied === c.id ? 'Copied' : 'Copy the number'}</button>
      </span>
    </li>)}</ul></section>
}

function EmployerMessage({ message }: { message: NonNullable<AnalyzeResponse['employer_message']> }) {
  const [state, setState] = useState<'' | 'copied' | 'failed'>('')
  async function copy() { try { await navigator.clipboard.writeText(`Subject: ${message.subject}\n\n${message.body}`); setState('copied') } catch { setState('failed') } }
  return <section className={styles.addEvidence}><h2>{message.title}</h2><p>{message.why}</p>
    <ol>{message.steps.map((step, i) => <li key={i}>{step}</li>)}</ol>
    <pre aria-label="Message to send" className={styles.help} style={{ whiteSpace: 'pre-wrap' }}>{`Subject: ${message.subject}\n\n${message.body}`}</pre>
    <em>{message.caution}</em>
    <span className={styles.actions}><button type="button" className={styles.secondaryButton} onClick={copy}>{state === 'copied' ? 'Copied' : 'Copy message'}</button></span>
    {state === 'failed' && <p role="alert" className={styles.error}>Could not copy automatically. Select the message above and copy it yourself.</p>}
  </section>
}

function Result({ result, input, onResult, onClear }: { result: AnalyzeResponse; input: Submitted; onResult: (result: AnalyzeResponse, input: Submitted) => void; onClear: () => void }) {
  const [reportOpen, setReportOpen] = useState(false)
  const band = result.risk_band
  const verdict = band ? verdictText[band] ?? { title: band.charAt(0).toUpperCase() + band.slice(1) } : null
  const canReport = Boolean(result.report_token && band && REPORTABLE_BANDS.has(band))
  return <section className={styles.result} aria-live="polite">
    <div className={styles.resultSide}>{band && verdict && <div className={`${styles.verdict} ${bandClass(band)}`}><h1>{verdict.title}</h1>{verdict.subline && <p className={styles.verdictSubline}>{verdict.subline}</p>}<p className={styles.score}><span>{Number.isInteger(result.overall_risk_score) ? result.overall_risk_score : result.overall_risk_score.toFixed(1)}</span> / 100</p><p className={styles.completeness}>{result.completeness_percentage}% information completeness</p></div>}
      {result.company_name?.trim() && <p className={styles.checkedCompany}>Checked: {result.company_name.trim()}</p>}
      {result.next_steps?.length > 0 && <section className={styles.guidance}><h2>What to do next</h2><ul>{result.next_steps.map((step, i) => <li key={i}>{step}</li>)}</ul>{(band === 'high risk' || band === 'insufficient evidence, verify manually') && <p className={styles.portalNote}>You can report this sender on the government's <a href="https://cybercrime.gov.in/" target="_blank" rel="noopener noreferrer">National Cyber Crime Reporting Portal</a>. If you have already paid, call 1930 first.</p>}</section>}
      <div className={styles.actions}>{canReport && <button onClick={() => setReportOpen(true)}>Share a suspected scam</button>}<button type="button" className={styles.secondaryButton} onClick={() => downloadReport(result)}>Download full report</button><button className={styles.secondaryButton} onClick={onClear}>Check another offer</button></div>
      {result.complaint_summary?.trim() && <Complaint summary={result.complaint_summary}/>}
    </div>
    <div className={styles.evidenceSide}><SafetyActions actions={result.safety_actions ?? []}/><WhyList result={result}/><EvidenceLedger checks={result.checks ?? []} meta={result.evidence_meta ?? []}/><SelfChecks checks={result.self_checks ?? []}/>{result.employer_message && <EmployerMessage message={result.employer_message}/>}<AddEvidence result={result} input={input} onResult={onResult}/></div>
    {reportOpen && canReport && result.report_token && <ReportDialog token={result.report_token} indicators={result.reportable_indicators ?? []} onClose={() => setReportOpen(false)}/>}
  </section>
}

function WithdrawPage() {
  const [code, setCode] = useState(''); const [message, setMessage] = useState(''); const [error, setError] = useState(''); const [busy, setBusy] = useState(false)
  async function send(event: FormEvent) { event.preventDefault(); setBusy(true); setError(''); setMessage(''); try { await withdrawReport({ code }); setMessage('Withdrawn. Your report no longer counts towards any warning.') } catch (err) { setError(err instanceof Error ? err.message : 'The code could not be accepted. Check it and try again.') } finally { setBusy(false) } }
  return <section className={styles.formPage}><h1>Withdraw a report</h1><p>Enter the one-time code you saved when submitting the report.</p><form onSubmit={send}><label>Withdrawal code<input value={code} onChange={e => setCode(e.target.value)} required autoComplete="off"/></label><button disabled={busy || !code.trim()}>{busy ? 'Withdrawing…' : 'Withdraw report'}</button></form>{message && <p role="status">{message}</p>}{error && <p role="alert" className={styles.error}>{error}</p>}</section>
}

function VerifyDisputePage() {
  // The code travels in the #fragment, which the browser never sends to a server; it is posted in a request body.
  const token = new URLSearchParams(window.location.hash.replace(/^#/, '')).get('token') ?? ''
  const [message, setMessage] = useState(''); const [error, setError] = useState(''); const [busy, setBusy] = useState(false)
  async function confirm() { setBusy(true); setError(''); setMessage(''); try { const r = await verifyDispute(token); setMessage(r.message); window.history.replaceState({}, '', '/verify-dispute') } catch (err) { setError(err instanceof Error ? err.message : 'That link is invalid or has expired.') } finally { setBusy(false) } }
  return <section className={styles.formPage}><h1>Confirm your dispute</h1>{token ? <><p>Confirm that you control this domain. The link works once and expires after 24 hours.</p><button onClick={confirm} disabled={busy || !!message}>{busy ? 'Confirming…' : 'Confirm domain'}</button></> : !message && <p>This page needs the link from the verification email.</p>}{message && <p role="status">{message}</p>}{error && <p role="alert" className={styles.error}>{error}</p>}</section>
}

function DisputePage() {
  const [kind, setKind] = useState<'upi'|'bank'|'phone'|'email'|'domain'>('domain'); const [value, setValue] = useState(''); const [email, setEmail] = useState(''); const [reason, setReason] = useState('our_business_detail'); const [message, setMessage] = useState(''); const [error, setError] = useState(''); const [busy, setBusy] = useState(false)
  async function send(event: FormEvent) { event.preventDefault(); setBusy(true); setError(''); setMessage(''); try { const result = await submitDispute({ indicator_type: kind, value, contact_email: email, reason_code: reason as DisputeRequest['reason_code'] }); setMessage(result.message) } catch (err) { setError(err instanceof Error ? err.message : 'The dispute could not be submitted.') } finally { setBusy(false) } }
  return <section className={styles.formPage}><h1>Dispute an indicator</h1><p>Disputes are reviewed. They do not remove warnings unless a domain is verified by a link sent to that domain.</p><form onSubmit={send}><label>Indicator type<select value={kind} onChange={e => setKind(e.target.value as typeof kind)}><option value="domain">Domain</option><option value="email">Email address</option><option value="upi">UPI ID</option><option value="bank">Bank account</option><option value="phone">Phone</option></select></label><label>Indicator value<input value={value} onChange={e => setValue(e.target.value)} required minLength={3} maxLength={320}/></label><label>Contact email<input type="email" value={email} onChange={e => setEmail(e.target.value)} required/></label>{kind === 'domain' && <p className={styles.help}>For a domain dispute, use an address at the same domain. A one-time verification link may be sent.</p>}<label>Reason<select value={reason} onChange={e => setReason(e.target.value)}><option value="our_business_detail">This is our business's own detail</option><option value="reported_in_error">It was reported in error</option><option value="someone_else_misused_it">Someone else misused it</option><option value="other">Other</option></select></label><p className={styles.help}>Please do not type offer letters, names or bank details here; we only keep this reason.</p><button disabled={busy}>{busy ? 'Submitting…' : 'Submit dispute'}</button></form>{message && <p role="status">{message}</p>}{error && <p role="alert" className={styles.error}>{error}</p>}</section>
}

function TrendChart({ dashboard }: { dashboard: InstitutionDashboard }) {
  const groups = useMemo(() => dashboard.weeks.map(week => dashboard.by_week_band.filter(row => row.week === week)), [dashboard])
  const numeric = dashboard.by_week_band.flatMap(row => typeof row.count === 'number' ? [row.count] : [])
  const max = Math.max(5, ...numeric)
  const bands: RiskBand[] = ['high risk', 'insufficient evidence, verify manually', 'likely legitimate']
  return <div className={styles.chartPanel}><div className={styles.chartLegend}>{bands.map((band, i) => <span key={band}><i className={`${styles.legendMark} ${[styles.highMark, styles.manualMark, styles.legitMark][i]}`}>{i === 2 && <svg className={styles.legendHatch} viewBox="0 0 16 12" aria-hidden="true"><defs><pattern id="legendHatchPattern" width="5" height="5" patternUnits="userSpaceOnUse"><rect width="5" height="5" fill="var(--obsidian)"/><path d="M-1 1 L1 -1 M0 5 L5 0 M4 6 L6 4" stroke="var(--graphite)" strokeWidth="1.5"/></pattern></defs><rect width="16" height="12" fill="url(#legendHatchPattern)" stroke="var(--graphite)"/></svg>}</i>{band}</span>)}</div><div className={styles.chartScroll}><svg className={styles.chart} viewBox="0 0 900 190" role="img" aria-labelledby="chart-title chart-desc"><title id="chart-title">Results by week</title><desc id="chart-desc">Grouped weekly counts for high risk, insufficient evidence, and likely legitimate results. Missing bars indicate suppressed counts below five; the weekly data export shows those cells as &lt;5.</desc><defs><pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse"><path d="M-1 1 L1 -1 M0 6 L6 0 M5 7 L7 5" stroke="var(--graphite)" strokeWidth="1.5"/></pattern></defs><line x1="38" y1="150" x2="890" y2="150" stroke="var(--graphite)"/>{groups.map((rows, wi) => { const x = 50 + wi * 70; return <g key={dashboard.weeks[wi]}><text x={x + 22} y="173" textAnchor="middle" className={styles.axisText}>{dashboard.weeks[wi].slice(5)}</text>{rows.map(row => { const bi = bands.indexOf(row.band); const n = typeof row.count === 'number' ? row.count : 0; const h = n / max * 110; const bx = x + bi * 19; const fill = bi === 0 ? 'var(--white)' : bi === 1 ? 'var(--obsidian)' : 'url(#hatch)'; return <rect key={row.band} x={bx} y={150 - h} width="13" height={Math.max(n ? 1 : 0, h)} fill={fill} stroke={bi === 1 ? 'var(--platinum)' : 'var(--graphite)'}><title>{row.band}, {row.count === '<5' ? '<5 results, value suppressed' : `${row.count} results`}, {dashboard.weeks[wi]}</title></rect> })}</g> })}</svg></div><p className={styles.help}>A missing bar means the count is below five and has been suppressed. The weekly data export shows these cells as &lt;5.</p></div>
}

const senderTypeLabels: Record<TopSender['indicator_type'], string> = {
  email: 'Email', domain: 'Email domain', upi: 'UPI ID', phone: 'Phone', bank: 'Bank account',
}

function SendersTable({ dashboard }: { dashboard: InstitutionDashboard }) {
  const senders = dashboard.top_senders ?? []
  return <section className={styles.sendersSection} aria-labelledby="senders-title">
    <div className={styles.sendersHead}><h2 id="senders-title">Reported senders</h2><a className={styles.exportLink} href={SENDERS_CSV_URL} download>Export warning list</a></div>
    <p className={styles.help}>Shown only after {dashboard.sender_threshold ?? 3} or more separate reports name the same sender, made on at least two different days.</p>
    {senders.length ? <div className={styles.ledgerWrap}><table className={styles.ledger} aria-label="Reported senders"><thead><tr><th scope="col">Sender</th><th scope="col">Type</th><th scope="col" className={styles.numeric}>Reports</th><th scope="col">Seen</th><th scope="col">Most common</th><th scope="col">Status</th></tr></thead><tbody>{senders.map(s => <tr className={styles.ledgerRow} key={`${s.indicator_type}:${s.indicator}`}>
      <th scope="row">{s.indicator}</th><td>{senderTypeLabels[s.indicator_type] ?? s.indicator_type}</td><td className={styles.numeric}>{s.reports}</td><td>{s.first_week === s.last_week ? s.first_week : `${s.first_week} – ${s.last_week}`}</td><td>{categoryLabels[s.most_common_category] ?? s.most_common_category}</td><td>{s.dispute_status ? <span className={styles.disputed}>Disputed by the company, under review</span> : '—'}</td>
    </tr>)}</tbody></table></div> : <p className={styles.emptyNote}>No sender has {dashboard.sender_threshold ?? 3} or more separate reports yet.</p>}
  </section>
}

function CategorySummary({ dashboard }: { dashboard: InstitutionDashboard }) {
  const rows = dashboard.category_summary ?? []
  const suppressedTitle = 'Counts under five are suppressed to protect privacy.'
  const cell = (n: number | '<5') => <td className={styles.numeric} title={n === '<5' ? suppressedTitle : undefined}>{n}</td>
  return <section className={styles.categorySection} aria-labelledby="categories-title">
    <div className={styles.sendersHead}><h2 id="categories-title">Scam categories</h2><a className={styles.exportLink} href={WEEKLY_CSV_URL} download>Export weekly data</a></div>
    <p className={styles.help}>Last 12 weeks. Trend compares the last 4 weeks with the 8 weeks before them.</p>
    <div className={styles.ledgerWrap}><table className={styles.ledger} aria-label="Scam categories"><thead><tr><th scope="col">Category</th><th scope="col" className={styles.numeric}>12 weeks</th><th scope="col" className={styles.numeric}>Last 4 weeks</th><th scope="col" className={styles.numeric}>Previous 8 weeks</th><th scope="col">Trend</th></tr></thead>
      <tbody>{rows.map(r => <tr key={r.category}><th scope="row">{categoryLabels[r.category] ?? r.category}</th>{cell(r.total)}{cell(r.last_4_weeks)}{cell(r.previous_8_weeks)}<td>{r.trend ?? '—'}</td></tr>)}</tbody></table></div>
  </section>
}

function DashboardPage() {
  const [dashboard, setDashboard] = useState<InstitutionDashboard | null>(null); const [error, setError] = useState(''); const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let active = true
    setError('')
    loadDashboard().then(data => { if (active) setDashboard(data) })
      .catch(err => { if (active) setError(err instanceof Error ? err.message : 'The dashboard could not be loaded.') })
    return () => { active = false }
  }, [attempt])
  return <section className={styles.dashboardPage}><h1>Scam trends</h1><p>Weekly results, scam categories and reported senders from checks on this site. Counts are checks, not verified unique people.</p>{!dashboard && !error && <p className={styles.help} role="status">Loading…</p>}{error && <><p role="alert" className={styles.error}>{error}</p><button type="button" className={styles.secondaryButton} onClick={() => setAttempt(n => n + 1)}>Try again</button></>}{dashboard && <div className={styles.dashboardResults}><SendersTable dashboard={dashboard}/><h2>Results by week</h2><TrendChart dashboard={dashboard}/><CategorySummary dashboard={dashboard}/></div>}</section>
}

const sourceStatusText: Record<string, string> = { current: 'Up to date', stale: 'Out of date', unknown: 'Date unknown' }

function SourcesPanel() {
  const [data, setData] = useState<Awaited<ReturnType<typeof loadSources>> | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => { let live = true; loadSources().then(d => { if (live) setData(d) }).catch(() => { if (live) setFailed(true) }); return () => { live = false } }, [])
  if (failed) return <section><h2>Data sources</h2><p>The data-source details could not be loaded right now.</p></section>
  if (!data) return null
  const on = Object.entries(data.optional_lookups).filter(([, v]) => v).length
  return <section><h2>Data sources and freshness</h2>
    <p>Rules version {data.scoring_model}. Dates show when each source was last refreshed; an old source can miss recent changes.</p>
    <ul>{data.sources.map(s => <li key={s.id}><strong>{s.name}:</strong> {sourceStatusText[s.status] ?? s.status}{s.updated ? `, refreshed ${s.updated} (${s.age_days} days ago)` : ''}. {s.detail}</li>)}</ul>
    <p>{on} optional online lookup{on === 1 ? ' is' : 's are'} switched on for this service.</p>
    {data.request_budgets.map(b => <p key={b.id}>The {b.id.replace('_', ' ')} lookup is {b.status === 'paused' ? 'paused for today (daily allowance used up)' : 'available'}.</p>)}
  </section>
}

function HowPage() {
  return <article className={styles.howPage}><h1>What this checks</h1><p className={styles.lede}>An automated review of specific signals in an offer. It helps you decide what to verify; it cannot prove who wrote a message or whether a job is real.</p>
    <section><h2>Who sent it</h2><p>For an original .eml, the service reads the recipient provider’s topmost Authentication-Results, DMARC, SPF and aligned DKIM, plus sender details. This verifies sender authentication as recorded by that mail provider, not message authorship. Pasted text and documents show only the domain claimed in the content.</p></section>
    <section><h2>Email domain</h2><p>Checks domain availability, age, mailbox type and lookalike signals. A passing result means those domain rules passed; it does not verify company identity.</p></section>
    <section><h2>Company registration</h2><p>Checks GSTIN structure, and we check the CIN against company registry records. A registry match means the CIN belongs to an active company with the same name; a different company name or an inactive status is flagged. GSTIN and CIN state codes are informational.</p></section>
    <section><h2>Payment request</h2><p>Looks for fee and deposit demands, nearby UPI details, and relevant urgency. A detected phrase does not prove that money changed hands. Salary, stipend and reimbursement context is excluded from standalone payment-demand detection.</p></section>
    <section><h2>Reports from other job seekers</h2><p>With consent, selected scammer-role indicators and a redacted wording fingerprint can be matched against reports. Evidence is bucketed, correlated evidence is capped, and community evidence alone cannot cause a high-risk verdict. Reports are not independently verified.</p></section>
    <section><h2>How to read the result</h2><p>Likely legitimate requires a passing domain, present non-failing registration and an external verification signal. Otherwise structural checks alone cannot establish legitimacy. A payment demand forces high risk. These are rules, not a trained model.</p></section>
    <section><h2>Planned and unavailable checks</h2><p>No additional future check is claimed in the current capability statements. Company registry records are looked up locally; this service does not query a registry over the network. Sender authentication is available for .eml uploads only. Other input types cannot authenticate the sender.</p></section>
    <SourcesPanel/>
    <section><h2>Privacy and limits</h2><p>The offer text and file aren’t stored. Analysis results are retained. Every check adds one anonymous count (week, result and scam category only; no text, contact details, file name or IP address) to the public Scam trends page, where any count below five is shown as &lt;5. These counts are kept for 24 months. Counts represent checks, not verified unique people.</p><p><a href="https://github.com/sohamsarode2007-lab/offer-internship-verification-shield/blob/main/docs/PRIVACY_DESIGN.md">Read the privacy design</a>. <a href="https://github.com/sohamsarode2007-lab/offer-internship-verification-shield/blob/main/CLAIMS.md">Read current capability claims</a>.</p></section>
  </article>
}

export default function App() {
  const [result, setResult] = useState<AnalyzeResponse | null>(null)
  const [input, setInput] = useState<Submitted>({ text: '', file: null })
  const show = (r: AnalyzeResponse, i: Submitted) => { setResult(r); setInput(i) }
  const path = window.location.pathname.replace(/\/$/, '') || '/'
  let page: React.ReactNode
  if (path === '/withdraw') page = <WithdrawPage/>
  else if (path === '/dispute') page = <DisputePage/>
  else if (path === '/verify-dispute') page = <VerifyDisputePage/>
  else if (path === '/dashboard') page = <DashboardPage/>
  else if (path === '/how-it-works') page = <HowPage/>
  else if (result && path === '/') page = <Result result={result} input={input} onResult={show} onClear={() => { setResult(null); setInput({ text: '', file: null }) }}/>
  else page = <Home onResult={show}/>
  return <Shell>{page}</Shell>
}
