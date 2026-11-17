import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup } from '@testing-library/react'
import App from './App'
import { CONSENT_TEXT, CONSENT_VERSION } from './consent'
import type { AnalyzeResponse, ReportableIndicator } from './api/types'
import * as api from './api/client'
import styles from './App.module.css'

vi.mock('./api/client', async importOriginal => {
  const actual = await importOriginal<typeof import('./api/client')>()
  return { ...actual, analyze: vi.fn(), submitReport: vi.fn(), withdrawReport: vi.fn(), submitDispute: vi.fn(), loadDashboard: vi.fn() }
})

const indicators: ReportableIndicator[] = [
  { id: 'upi:one', indicator_type: 'upi', masked: 'rky.ver•••@ybl' },
  { id: 'phone:two', indicator_type: 'phone', masked: '+91 ••••••1234' },
]
function payload(overrides: Partial<AnalyzeResponse> = {}): AnalyzeResponse {
  return {
    overall_risk_score: 72, completeness_percentage: 80, checks: [], summary: 'Analysis completed.',
    risk_band: 'high risk', risk_factors: [], scoring_model: 'rule_based_v2', next_steps: [],
    complaint_summary: '', report_token: null, reportable_indicators: [], ...overrides,
  }
}
async function showResult(data: AnalyzeResponse) {
  vi.mocked(api.analyze).mockResolvedValueOnce(data)
  const user = userEvent.setup()
  render(<App />)
  await user.type(screen.getByLabelText('Paste offer text'), 'Test offer text')
  await user.click(screen.getByRole('button', { name: 'Check offer' }))
  return user
}
afterEach(cleanup)
beforeEach(() => { vi.clearAllMocks(); window.history.replaceState({}, '', '/') })

describe('analysis result', () => {
  it.each([
    { band: 'high risk', title: 'High risk', className: styles.highRisk },
    { band: 'insufficient evidence, verify manually', title: 'Insufficient evidence', className: styles.manual },
    { band: 'likely legitimate', title: 'Likely legitimate', className: styles.likely },
  ])('renders the verdict plate in sentence case ($title)', async ({ band, title, className }) => {
    await showResult(payload({ risk_band: band }))
    const heading = screen.getByRole('heading', { name: title })
    expect(heading.parentElement).toHaveClass(className)
    expect(screen.getByText('72', { exact: true })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: band })).not.toBeInTheDocument()
  })

  it('shows "Verify manually before you proceed" under an insufficient-evidence verdict', async () => {
    await showResult(payload({ risk_band: 'insufficient evidence, verify manually' }))
    const plate = screen.getByRole('heading', { name: 'Insufficient evidence' }).parentElement!
    expect(within(plate).getByText('Verify manually before you proceed')).toHaveClass(styles.verdictSubline)
  })

  it.each([
    { band: 'high risk', shown: true },
    { band: 'insufficient evidence, verify manually', shown: true },
    { band: 'likely legitimate', shown: false },
  ])('offers "Report this scam" only for high risk or insufficient evidence ($band)', async ({ band, shown }) => {
    await showResult(payload({ risk_band: band, report_token: 'signed-report-token-is-long-enough', reportable_indicators: indicators }))
    expect(Boolean(screen.queryByRole('button', { name: 'Report this scam' }))).toBe(shown)
  })

  it('lists plain-language reasons with the score impact in a right-aligned column', async () => {
    await showResult(payload({ risk_band: 'insufficient evidence, verify manually', reasons: [
      { text: 'The company is listed as struck off in the company register', impact: '+25' },
      { text: "The company's email domain exists and can receive email", impact: '−10' },
      { text: "We couldn't verify this company's registration, so we can't call it legitimate yet.", impact: '+16' },
    ] }))
    const why = screen.getByRole('table', { name: 'Why' })
    const rows = within(why).getAllByRole('row').slice(1)
    expect(rows).toHaveLength(3)
    expect(within(rows[2]).getByText("We couldn't verify this company's registration, so we can't call it legitimate yet.")).toBeInTheDocument()
    const impact = within(rows[0]).getByText('+25')
    expect(impact).toHaveClass(styles.impact)
    const css = readFileSync(resolve(__dirname, 'App.module.css'), 'utf8')
    expect(css).toMatch(/\.whyTable td\.impact \{[^}]*text-align: right/)
    for (const engineWord of ['offset', 'score floor', "'likely legitimate'"]) expect(why.textContent).not.toContain(engineWord)
  })

  it('shows the demo-fixture note as small steel text', async () => {
    await showResult(payload({ checks: [{ check_name: 'domain_verification', status: 'pass', details: '[DEMO FIXTURE — not a live DNS result] x.example.' }] }))
    const note = screen.getByText('Demo fixture, not a live check')
    expect(note.tagName).toBe('SPAN')
    const css = readFileSync(resolve(__dirname, 'App.module.css'), 'utf8')
    expect(css).toMatch(/\.demoNote \{[^}]*color: var\(--steel\)[^}]*font-size: 12px/)
  })

  it('renders ledger names, status glyphs and details in API order', async () => {
    await showResult(payload({ checks: [
      { check_name: 'sender_authentication', status: 'pass', details: 'DMARC and aligned DKIM passed.' },
      { check_name: 'payment_detection', status: 'fail', details: 'Payment demand detected.' },
      { check_name: 'community_reports', status: 'insufficient_information', details: 'No matching reports.' },
      { check_name: 'domain_verification', status: 'not_applicable' },
    ] }))
    const ledger = screen.getByRole('table', { name: 'Evidence' })
    expect(within(ledger).getByText('Who sent it')).toBeInTheDocument()
    expect(within(ledger).getByText('Passed')).toBeInTheDocument()
    expect(within(ledger).getByText('✕')).toBeInTheDocument()
    expect(within(ledger).getByText('Not enough information')).toBeInTheDocument()
    expect(within(ledger).getByText('Not applicable')).toBeInTheDocument()
    await userEvent.click(within(ledger).getAllByText('Details')[0])
    expect(within(ledger).getByText('DMARC and aligned DKIM passed.')).toBeInTheDocument()
  })

  it('shows the checked company name under the verdict plate, in steel', async () => {
    await showResult(payload({ risk_band: 'likely legitimate', company_name: 'Quillmere Software Private Limited' }))
    const line = screen.getByText('Checked: Quillmere Software Private Limited')
    expect(line).toHaveClass(styles.checkedCompany)
    const plate = screen.getByRole('heading', { name: 'Likely legitimate' }).parentElement!
    expect(plate.nextElementSibling).toBe(line)
    const css = readFileSync(resolve(__dirname, 'App.module.css'), 'utf8')
    expect(css).toMatch(/\.checkedCompany \{[^}]*color: var\(--steel\)/)
  })

  it.each([null, undefined, '', '   '])('hides the company line when no name was extracted (%j)', async name => {
    await showResult(payload({ company_name: name as string | null | undefined }))
    expect(screen.queryByText(/^Checked:/)).not.toBeInTheDocument()
  })

  it.each(['high risk', 'insufficient evidence, verify manually'])('links to the national cyber crime portal for %s', async band => {
    await showResult(payload({ risk_band: band, next_steps: ['Do not pay.'] }))
    const link = screen.getByRole('link', { name: 'National Cyber Crime Reporting Portal' })
    expect(link).toHaveAttribute('href', 'https://cybercrime.gov.in/')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('does not show the portal link for a likely legitimate result', async () => {
    await showResult(payload({ risk_band: 'likely legitimate', next_steps: ['Confirm the sender independently.'] }))
    expect(screen.queryByRole('link', { name: 'National Cyber Crime Reporting Portal' })).not.toBeInTheDocument()
  })

  it('labels demo fixture evidence', async () => {
    await showResult(payload({ checks: [{ check_name: 'domain_verification', status: 'pass', details: '[DEMO FIXTURE — not a live DNS result] emberlakeanalytics.example.' }] }))
    expect(screen.getByText('Demo fixture, not a live check')).toBeInTheDocument()
  })

  it('hides Why, complaint summary and report controls when their fields are absent', async () => {
    await showResult(payload({ risk_band: null, risk_factors: [], next_steps: [], complaint_summary: '', report_token: null }))
    expect(screen.queryByRole('heading', { name: 'Why' })).not.toBeInTheDocument()
    expect(screen.queryByText('/ 100')).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Report it to the police' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Report this scam' })).not.toBeInTheDocument()
  })
})

describe('interface errors', () => {
  it.each([
    [413, 'This file is over 10 MB. Upload a smaller file or paste the text instead.'],
    [415, 'This file type isn’t supported. Use PDF, PNG, JPG or .eml.'],
    [422, "We couldn't read any text in this file. Try a clearer image or paste the text."],
    [429, 'Too many checks in a minute. Wait a moment and try again.'],
    [0, "The server can't be reached. Check your connection and try again."],
  ])('shows the mapped message for status %s', async (status, message) => {
    vi.mocked(api.analyze).mockRejectedValueOnce(new api.ApiError(status, message))
    const user = userEvent.setup(); render(<App />)
    await user.type(screen.getByLabelText('Paste offer text'), 'Offer text')
    await user.click(screen.getByRole('button', { name: 'Check offer' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(message)
  })
})

describe('Scam trends page', () => {
  const dashboardData = {
    institution: 'Public', sender_threshold: 3, weeks: ['2026-W46'], by_week_band: [], by_week_category: [],
    category_summary: [
      { category: 'registration_fee', total: 61, last_4_weeks: 28, previous_8_weeks: 33, trend: 'Rising' },
      { category: 'sender_spoofing', total: '<5', last_4_weeks: '<5', previous_8_weeks: '<5', trend: null },
    ],
    top_senders: [
      { indicator: 'pl•••@gmail.com', indicator_type: 'email', reports: 12, first_week: '2026-W36', last_week: '2026-W46', most_common_category: 'free_mailbox_impersonation', dispute_status: null },
      { indicator: 'brightpath-hiring.example', indicator_type: 'domain', reports: 4, first_week: '2026-W40', last_week: '2026-W44', most_common_category: 'registration_fee', dispute_status: 'disputed by the company, under review' },
    ],
  } as const
  it('loads without a key and shows the senders table above the chart', async () => {
    vi.mocked(api.loadDashboard).mockResolvedValueOnce(structuredClone(dashboardData) as never)
    window.history.replaceState({}, '', '/dashboard')
    render(<App />)
    expect(await screen.findByRole('heading', { name: 'Scam trends' })).toBeInTheDocument()
    expect(screen.queryByLabelText(/API key/i)).not.toBeInTheDocument()
    const senders = await screen.findByRole('heading', { name: 'Reported senders' })
    const chart = screen.getByRole('heading', { name: 'Results by week' })
    expect(senders.compareDocumentPosition(chart) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(screen.getByText('Shown only after 3 or more people report the same sender.')).toBeInTheDocument()
    const table = screen.getByRole('table', { name: 'Reported senders' })
    expect(within(table).getByText('pl•••@gmail.com')).toBeInTheDocument()
    expect(within(table).getByText('12')).toBeInTheDocument()
    expect(within(table).getByText('Disputed by the company, under review')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Export warning list' })).toHaveAttribute('href', expect.stringContaining('/trends/senders.csv'))
    expect(vi.mocked(api.loadDashboard)).toHaveBeenCalledWith()
  })
  it('shows one row per category with totals and a trend word instead of a week grid', async () => {
    vi.mocked(api.loadDashboard).mockResolvedValueOnce(structuredClone(dashboardData) as never)
    window.history.replaceState({}, '', '/dashboard')
    render(<App />)
    const table = await screen.findByRole('table', { name: 'Scam categories' })
    const headers = within(table).getAllByRole('columnheader').map(h => h.textContent)
    expect(headers).toEqual(['Category', '12 weeks', 'Last 4 weeks', 'Previous 8 weeks', 'Trend'])
    const [, reg, spoof] = within(table).getAllByRole('row')
    expect(within(reg).getByRole('rowheader')).toHaveTextContent('Registration fee')
    expect(reg).toHaveTextContent('61'); expect(reg).toHaveTextContent('Rising')
    expect(within(spoof).getAllByText('<5')).toHaveLength(3)
    expect(within(spoof).getByText('—')).toBeInTheDocument()
    expect(screen.queryByRole('table', { name: 'Scam categories by week' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Export weekly data' })).toHaveAttribute('href', expect.stringContaining('/trends/weekly.csv'))
  })
  it('names the page in the navigation and has no college-code field', () => {
    render(<App />)
    expect(screen.getByRole('link', { name: 'Scam trends' })).toHaveAttribute('href', '/dashboard')
    expect(screen.queryByLabelText(/college/i)).not.toBeInTheDocument()
  })
})

describe('community report consent', () => {
  it('matches the version 4 text in the privacy design', () => {
    const path = [resolve(process.cwd(), '../docs/PRIVACY_DESIGN.md'), resolve(process.cwd(), 'docs/PRIVACY_DESIGN.md')].find(existsSync)!
    const doc = readFileSync(path, 'utf8')
    const quote = doc.match(/> Share these details[\s\S]*?so it can warn other job seekers\./)?.[0]
    expect(quote).toBeTruthy()
    expect(quote!.split('\n').map(line => line.replace(/^>\s?/, '').trim()).join(' ').replace(/\s+/g, ' ')).toBe(CONSENT_TEXT)
    expect(CONSENT_VERSION).toBe(4)
    expect(doc).toContain('version `4`')
    expect(CONSENT_TEXT.endsWith("The public scam-trends page will show these details in masked form so it can warn other job seekers.")).toBe(true)
  })

  it('allows deselection, requires consent and does not store the withdrawal code', async () => {
    vi.mocked(api.submitReport).mockResolvedValueOnce({ status: 'reported', withdrawal_code: 'once-only-secret-code-123456' })
    const user = await showResult(payload({ report_token: 'signed-report-token-is-long-enough', reportable_indicators: indicators }))
    await user.click(screen.getByRole('button', { name: 'Report this scam' }))
    const firstIndicator = screen.getByRole('checkbox', { name: /Payment UPI ID/ })
    await user.click(firstIndicator)
    await user.click(screen.getByRole('button', { name: 'Continue' }))
    expect(screen.getByRole('button', { name: 'Report scam' })).toBeDisabled()
    await user.click(screen.getByLabelText(CONSENT_TEXT))
    expect(screen.getByRole('button', { name: 'Report scam' })).toBeEnabled()
    await user.click(screen.getByRole('button', { name: 'Report scam' }))
    expect(await screen.findByText('once-only-secret-code-123456')).toBeInTheDocument()
    expect(vi.mocked(api.submitReport)).toHaveBeenCalledWith(expect.objectContaining({ consent: true, consent_version: 4, selected_indicators: ['phone:two'] }))
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
  })
})

describe('add evidence and check again', () => {
  const hints = [{ id: 'company_identifiers', title: 'Add the company\'s registration details', why: 'A CIN can be compared.', how: 'Look in the footer.' }]

  it('shows hint cards only when the server returned hints', async () => {
    await showResult(payload({ evidence_hints: [] }))
    expect(screen.queryByText('Make this check stronger')).toBeNull()
    cleanup()
    await showResult(payload({ evidence_hints: hints }))
    expect(await screen.findByText('Make this check stronger')).toBeTruthy()
    expect(screen.getByText(/registration details/)).toBeTruthy()
  })

  it('sends the earlier text together with the new text, then shows the new result', async () => {
    const user = await showResult(payload({ evidence_hints: hints, overall_risk_score: 40 }))
    vi.mocked(api.analyze).mockResolvedValueOnce(payload({ evidence_hints: [], overall_risk_score: 5, risk_band: 'likely legitimate' }))
    await user.type(await screen.findByLabelText('More details to add'), 'CIN: U74999DL2016PTC298345')
    await user.click(screen.getByRole('button', { name: 'Check again with this' }))
    const [text, file] = vi.mocked(api.analyze).mock.calls[1]
    expect(text).toBe('Test offer text\n\nCIN: U74999DL2016PTC298345')
    expect(file).toBeNull()
    expect(await screen.findByText('Likely legitimate')).toBeTruthy()
  })

  it('asks for something to add instead of sending an empty re-check', async () => {
    const user = await showResult(payload({ evidence_hints: hints }))
    await user.click(await screen.findByRole('button', { name: 'Check again with this' }))
    expect((await screen.findByRole('alert')).textContent).toMatch(/Add some text or choose a file/)
    expect(vi.mocked(api.analyze)).toHaveBeenCalledTimes(1)
  })
})
