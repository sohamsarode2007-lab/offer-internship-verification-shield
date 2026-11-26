import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { render, screen, waitFor, within } from '@testing-library/react'
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
  return { ...actual, analyze: vi.fn(), submitReport: vi.fn(), withdrawReport: vi.fn(), submitDispute: vi.fn(), verifyDispute: vi.fn(), loadDashboard: vi.fn(), loadConfig: vi.fn(), loadSources: vi.fn() }
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
beforeEach(() => { vi.clearAllMocks(); vi.mocked(api.loadConfig).mockResolvedValue({ link_lookups: false }); window.history.replaceState({}, '', '/') })

describe('data sources panel', () => {
  const data = { scoring_model: 'rule_based_v2', optional_lookups: { link_lookups: false, careers_page: true },
    sources: [{ id: 'company_registry', name: 'Company registry snapshot (local copy)', updated: '2026-08-01', age_days: 112, status: 'stale' as const, detail: 'Source label MCA_CSV.' },
              { id: 'employer_advisories', name: 'Employer fraud advisories (read by hand)', updated: null, age_days: null, status: 'unknown' as const, detail: '0 employers.' }],
    request_budgets: [{ id: 'web_risk', status: 'available' as const }] }
  it('shows each source with its age and status, never calling an undated one fresh', async () => {
    window.history.replaceState({}, '', '/how-it-works')
    vi.mocked(api.loadSources).mockResolvedValueOnce(data)
    render(<App />)
    expect(await screen.findByText(/Out of date, refreshed 2026-08-01 \(112 days ago\)/)).toBeTruthy()
    expect(screen.getByText(/Date unknown/)).toBeTruthy()
    expect(screen.getByText(/1 optional online lookup is switched on/)).toBeTruthy()
    expect(screen.getByText(/web risk lookup is available/)).toBeTruthy()
    expect(screen.queryByText(/3000/)).toBeNull()
  })
  it('says so when the details cannot be loaded', async () => {
    window.history.replaceState({}, '', '/how-it-works')
    vi.mocked(api.loadSources).mockRejectedValueOnce(new Error('x'))
    render(<App />)
    expect(await screen.findByText(/could not be loaded right now/)).toBeTruthy()
  })
})

describe('link lookup consent', () => {
  async function home(enabled: boolean) {
    vi.mocked(api.loadConfig).mockResolvedValue({ link_lookups: enabled })
    vi.mocked(api.analyze).mockResolvedValue(payload())
    const user = userEvent.setup()
    render(<App />)
    await user.type(screen.getByLabelText('Paste offer text'), 'Offer https://x.example/a')
    return user
  }
  it('shows no consent box when the server has the feature off', async () => {
    await home(false)
    expect(screen.queryByRole('checkbox')).toBeNull()
  })
  it('is unchecked by default and sends nothing extra when left unchecked', async () => {
    const user = await home(true)
    const box = await screen.findByRole('checkbox')
    expect((box as HTMLInputElement).checked).toBe(false)
    await user.click(screen.getByRole('button', { name: 'Check offer' }))
    expect(vi.mocked(api.analyze)).toHaveBeenCalledWith('Offer https://x.example/a', null)
  })
  it('sends the flag only after the person ticks the box', async () => {
    const user = await home(true)
    await user.click(await screen.findByRole('checkbox'))
    await user.click(screen.getByRole('button', { name: 'Check offer' }))
    expect(vi.mocked(api.analyze)).toHaveBeenCalledWith('Offer https://x.example/a', null, true)
  })
})

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
  ])('offers "Share a suspected scam" only for high risk or insufficient evidence ($band)', async ({ band, shown }) => {
    await showResult(payload({ risk_band: band, report_token: 'signed-report-token-is-long-enough', reportable_indicators: indicators }))
    expect(Boolean(screen.queryByRole('button', { name: 'Share a suspected scam' }))).toBe(shown)
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

  it('says a likely-legitimate result is not proof and points to the employer’s own website', async () => {
    await showResult(payload({ risk_band: 'likely legitimate' }))
    expect(screen.getByText(/Not proof\. Confirm through the employer’s own website/)).toBeInTheDocument()
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

  it('renders matched safety actions with urgent styling and recovery links', async () => {
    await showResult(payload({ safety_actions: [
      { id: 'payment', title: 'Do not pay', urgent: true, steps: ['Do not pay a fee.'] },
      { id: 'report', title: 'If you have lost money or shared details', urgent: true,
        steps: ['Contact your bank or payment app immediately.'], helpline: '1930', url: 'https://cybercrime.gov.in/' },
    ] }))
    const section = screen.getByRole('region', { name: 'Safety steps' })
    expect(within(section).getByText('Important: Do not pay')).toBeInTheDocument()
    expect(within(section).getByRole('link', { name: 'Call 1930' })).toHaveAttribute('href', 'tel:1930')
    expect(within(section).getByRole('link', { name: 'National Cyber Crime Reporting Portal' })).toHaveAttribute('href', 'https://cybercrime.gov.in/')
    expect(within(section).getByText('Contact your bank or payment app immediately.')).toBeInTheDocument()
    expect(section.querySelector('ul')).toHaveClass(styles.safetyCards)
  })

  it('hides Why, complaint summary and report controls when their fields are absent', async () => {
    await showResult(payload({ risk_band: null, risk_factors: [], next_steps: [], complaint_summary: '', report_token: null }))
    expect(screen.queryByRole('heading', { name: 'Why' })).not.toBeInTheDocument()
    expect(screen.queryByText('/ 100')).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Report it to the police' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Share a suspected scam' })).not.toBeInTheDocument()
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
    expect(screen.getByText('Shown only after 3 or more separate reports name the same sender, made on at least two different days.')).toBeInTheDocument()
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

  it('allows a wording-only report when every detail is unticked', async () => {
    vi.mocked(api.submitReport).mockResolvedValueOnce({ status: 'reported', withdrawal_code: 'wording-only-code-1234567890' })
    const user = await showResult(payload({ report_token: 'signed-report-token-is-long-enough', reportable_indicators: indicators }))
    await user.click(screen.getByRole('button', { name: 'Share a suspected scam' }))
    for (const box of screen.getAllByRole('checkbox')) await user.click(box)
    await user.click(screen.getByRole('button', { name: 'Continue' }))
    expect(screen.getByRole('button', { name: 'Report scam' })).toBeDisabled()
    await user.click(screen.getByLabelText(CONSENT_TEXT))
    await user.click(screen.getByRole('button', { name: 'Report scam' }))
    expect(await screen.findByText('wording-only-code-1234567890')).toBeInTheDocument()
    expect(vi.mocked(api.submitReport)).toHaveBeenCalledWith(expect.objectContaining({ selected_indicators: [] }))
  })

  it('allows deselection, requires consent and does not store the withdrawal code', async () => {
    vi.mocked(api.submitReport).mockResolvedValueOnce({ status: 'reported', withdrawal_code: 'once-only-secret-code-123456' })
    const user = await showResult(payload({ report_token: 'signed-report-token-is-long-enough', reportable_indicators: indicators }))
    await user.click(screen.getByRole('button', { name: 'Share a suspected scam' }))
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

  it('clears the add-evidence box after a successful re-check when hints remain', async () => {
    const user = await showResult(payload({ evidence_hints: hints, overall_risk_score: 40 }))
    vi.mocked(api.analyze).mockResolvedValueOnce(payload({ evidence_hints: hints, overall_risk_score: 35 }))
    const box = await screen.findByLabelText('More details to add') as HTMLTextAreaElement
    await user.type(box, 'CIN: U74999DL2016PTC298345')
    await user.click(screen.getByRole('button', { name: 'Check again with this' }))
    await waitFor(() => expect(box.value).toBe(''))
  })

  it('asks for something to add instead of sending an empty re-check', async () => {
    const user = await showResult(payload({ evidence_hints: hints }))
    await user.click(await screen.findByRole('button', { name: 'Check again with this' }))
    expect((await screen.findByRole('alert')).textContent).toMatch(/Add some text or choose a file/)
    expect(vi.mocked(api.analyze)).toHaveBeenCalledTimes(1)
  })

  describe('self checks', () => {
    const check = { id: 'udyam', title: 'Check this Udyam number yourself', number: 'UDYAM-MH-12-1234567',
      url: 'https://udyamregistration.gov.in/Udyam_Verify.aspx', why: 'We have not verified it.', steps: ['Open the page.', 'Type the captcha.'], caution: 'A match shows the number exists.' }
    it('shows nothing when there are no self checks', async () => {
      await showResult(payload({ self_checks: [] }))
      expect(screen.queryByRole('heading', { name: 'Check it yourself' })).toBeNull()
    })
    it('shows the number, the steps and a safe link to the official page', async () => {
      await showResult(payload({ self_checks: [check] }))
      expect(screen.getByText('UDYAM-MH-12-1234567')).toBeTruthy()
      const link = screen.getByRole('link', { name: 'Open the Udyam verification page' })
      expect(link.getAttribute('href')).toBe(check.url)
      expect(link.getAttribute('rel')).toContain('noopener')
      expect(screen.getByText('Type the captcha.')).toBeTruthy()
    })
  })

  describe('safety actions', () => {
    const report = { id: 'report', title: 'If you have lost money or shared details', steps: ['Call 1930 straight away.'], urgent: true, helpline: '1930', url: 'https://cybercrime.gov.in/' }
    it('shows nothing when there are no safety actions', async () => {
      await showResult(payload({ safety_actions: [] }))
      expect(screen.queryByRole('heading', { name: 'Protect yourself now' })).toBeNull()
    })
    it('shows the steps, a call link and the portal link', async () => {
      await showResult(payload({ safety_actions: [report] }))
      expect(screen.getByText('Call 1930 straight away.')).toBeTruthy()
      expect(screen.getByRole('link', { name: 'Call 1930' }).getAttribute('href')).toBe('tel:1930')
      const portal = screen.getAllByRole('link', { name: 'National Cyber Crime Reporting Portal' }).find(l => l.closest('[aria-label="Safety steps"]'))
      expect(portal?.getAttribute('href')).toBe('https://cybercrime.gov.in/')
      expect(portal?.getAttribute('rel')).toContain('noopener')
    })
  })

  describe('full report download', () => {
    it('offers a download button and builds the file in the browser', async () => {
      const create = vi.fn(() => 'blob:x'); const revoke = vi.fn()
      Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke })
      const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
      const user = await showResult(payload({}))
      await user.click(screen.getByRole('button', { name: 'Download full report' }))
      expect(create).toHaveBeenCalledTimes(1)
      expect(click).toHaveBeenCalled()
      expect(revoke).not.toHaveBeenCalled()      // revoking straight away cancels the download in Safari and Firefox
      await new Promise(resolve => setTimeout(resolve, 0))
      expect(revoke).not.toHaveBeenCalled()
      click.mockRestore()
    })
  })

  describe('evidence source line', () => {
    it('shows source, score effect and confidence for a check', async () => {
      await showResult(payload({
        checks: [{ check_name: 'domain_verification', status: 'fail', score: 100, details: 'bad' }],
        evidence_meta: [{ check_name: 'domain_verification', source: 'dns_lookup', affects: 'score', confidence: 'medium', freshness: 'live at check time', rule_version: 'rule_based_v2', checked_at: '2026-11-19T09:00:00Z' }],
      }))
      expect(screen.getByText(/Source: DNS lookup · affects the score · confidence: medium/)).toBeInTheDocument()
    })
    it('says "not enough to tell" for an unknown check', async () => {
      await showResult(payload({
        checks: [{ check_name: 'gstin_verification', status: 'insufficient_information', score: null, details: 'none' }],
        evidence_meta: [{ check_name: 'gstin_verification', source: 'offer_text_and_local_registry_snapshot', affects: 'context', confidence: 'none', freshness: 'x', rule_version: 'rule_based_v2', checked_at: 'x' }],
      }))
      expect(screen.getByText(/no score effect · confidence: not enough to tell/)).toBeInTheDocument()
    })
  })
})


describe('dispute verification page', () => {
  it('posts the code from the fragment in a request body and removes it from the address bar', async () => {
    window.history.replaceState({}, '', '/verify-dispute#token=abcdefghijklmnopqrstuvwxyz')
    vi.mocked(api.verifyDispute).mockResolvedValueOnce({ status: 'domain_verified', message: 'Domain is suppressed while the dispute is under review.' })
    render(<App />)
    expect(vi.mocked(api.verifyDispute)).not.toHaveBeenCalled()       // nothing is sent until the person confirms
    await userEvent.click(screen.getByRole('button', { name: 'Confirm domain' }))
    expect(vi.mocked(api.verifyDispute)).toHaveBeenCalledWith('abcdefghijklmnopqrstuvwxyz')
    expect(await screen.findByText(/Domain is suppressed/)).toBeInTheDocument()
    expect(screen.queryByText(/needs the link from the verification email/)).toBeNull()
    expect(window.location.hash).toBe('')
  })
  it('asks for the email link when there is no code', () => {
    window.history.replaceState({}, '', '/verify-dispute')
    render(<App />)
    expect(screen.getByText(/needs the link from the verification email/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Confirm domain' })).toBeNull()
  })
})

describe('upload and copy feedback', () => {
  it('states the .eml rule up front and warns when .eml is mixed with other files', async () => {
    const user = userEvent.setup(); render(<App />)
    expect(screen.getByText(/Choose up to 5 files \(PDF, image or .txt\), or one .eml/)).toBeInTheDocument()
    expect(screen.getByText(/a pass is never counted as proof/)).toBeInTheDocument()
    expect(screen.queryByText(/who actually sent it/)).toBeNull()
    await user.upload(screen.getByLabelText(/Choose up to 5 files/), [new File(['a'], 'a.eml'), new File(['b'], 'b.txt')])
    expect(await screen.findByText(/must be uploaded on its own/)).toBeInTheDocument()
  })
  it('says when more than 5 files were picked', async () => {
    const user = userEvent.setup(); render(<App />)
    await user.upload(screen.getByLabelText(/Choose up to 5 files/), Array.from({ length: 7 }, (_, i) => new File(['x'], `f${i}.txt`)))
    expect(await screen.findByText('Only the first 5 of 7 files were kept.')).toBeInTheDocument()
  })
  it('confirms a copy, and says so when copying is blocked', async () => {
    const user = userEvent.setup()
    await showResult(payload({ risk_band: 'High', complaint_summary: 'Summary text' }))
    const write = vi.fn().mockResolvedValueOnce(undefined).mockRejectedValueOnce(new Error('blocked'))
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: write }, configurable: true })
    await user.click(screen.getByRole('button', { name: 'Copy summary' }))
    expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Copied' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not copy automatically')
  })
  it('shows copy feedback and error state when copying withdrawal code', async () => {
    vi.mocked(api.submitReport).mockResolvedValueOnce({ status: 'reported', withdrawal_code: 'withdraw-code-12345' })
    const user = await showResult(payload({ report_token: 'signed-report-token-is-long-enough', reportable_indicators: [] }))
    const write = vi.fn().mockResolvedValueOnce(undefined).mockRejectedValueOnce(new Error('blocked'))
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: write }, configurable: true })
    await user.click(screen.getByRole('button', { name: 'Share a suspected scam' }))
    await user.click(screen.getByRole('button', { name: 'Continue' }))
    await user.click(screen.getByLabelText(CONSENT_TEXT))
    await user.click(screen.getByRole('button', { name: 'Report scam' }))
    await user.click(await screen.findByRole('button', { name: 'Copy code' }))
    expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Copied' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not copy automatically')
  })
  it('lets the dashboard be retried after a failed load', async () => {
    vi.mocked(api.loadDashboard).mockRejectedValueOnce(new Error('The dashboard could not be loaded.'))
      .mockResolvedValueOnce({ institution: 'Public', sender_threshold: 3, weeks: [], by_week_band: [], by_week_category: [], category_summary: [], top_senders: [] } as never)
    window.history.replaceState({}, '', '/dashboard')
    const user = userEvent.setup(); render(<App />)
    expect(await screen.findByRole('alert')).toHaveTextContent('could not be loaded')
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
    expect(vi.mocked(api.loadDashboard)).toHaveBeenCalledTimes(2)
  })
})

describe('employer confirmation message', () => {
  const employer_message = { title: 'Ask the company to confirm this offer', why: 'The surest check is to ask the employer directly.', steps: ['Find the company website yourself.'], subject: 'Please confirm an offer made in your company\'s name', body: 'Hello,\n\nI have received an offer that names Acme.', caution: 'A reply from the same address as the offer proves nothing.' }
  it('shows the message and copies subject and body together', async () => {
    const user = userEvent.setup()
    await showResult(payload({ employer_message }))
    const write = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: write }, configurable: true })
    expect(screen.getByRole('heading', { name: 'Ask the company to confirm this offer' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Copy message' }))
    expect(write).toHaveBeenCalledWith(expect.stringContaining('Subject: Please confirm an offer'))
    expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument()
  })
  it('is absent when the server sent none', async () => {
    await showResult(payload({ employer_message: null }))
    expect(screen.queryByRole('heading', { name: 'Ask the company to confirm this offer' })).toBeNull()
  })
})
