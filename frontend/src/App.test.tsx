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
    { band: 'high risk', className: styles.highRisk },
    { band: 'insufficient evidence, verify manually', className: styles.manual },
    { band: 'likely legitimate', className: styles.likely },
  ])('renders the  verdict plate', async ({ band, className }) => {
    await showResult(payload({ risk_band: band }))
    const heading = screen.getByRole('heading', { name: band })
    expect(heading.parentElement).toHaveClass(className)
    expect(screen.getByText('72', { exact: true })).toBeInTheDocument()
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
    const plate = screen.getByRole('heading', { name: 'likely legitimate' }).parentElement!
    expect(plate.nextElementSibling).toBe(line)
    const css = readFileSync(resolve(__dirname, 'App.module.css'), 'utf8')
    expect(css).toMatch(/\.checkedCompany \{[^}]*color: var\(--steel\)/)
  })

  it.each([null, undefined, '', '   '])('hides the company line when no name was extracted (%j)', async name => {
    await showResult(payload({ company_name: name as string | null | undefined }))
    expect(screen.queryByText(/^Checked:/)).not.toBeInTheDocument()
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

describe('community report consent', () => {
  it('matches the version 2 text in the privacy design', () => {
    const path = [resolve(process.cwd(), '../docs/PRIVACY_DESIGN.md'), resolve(process.cwd(), 'docs/PRIVACY_DESIGN.md')].find(existsSync)!
    const doc = readFileSync(path, 'utf8')
    const quote = doc.match(/> Share these details[\s\S]*?code we give you\./)?.[0]
    expect(quote).toBeTruthy()
    expect(quote!.split('\n').map(line => line.replace(/^>\s?/, '').trim()).join(' ').replace(/\s+/g, ' ')).toBe(CONSENT_TEXT)
    expect(CONSENT_VERSION).toBe(2)
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
    expect(vi.mocked(api.submitReport)).toHaveBeenCalledWith(expect.objectContaining({ consent: true, consent_version: 2, selected_indicators: ['phone:two'] }))
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
  })
})
