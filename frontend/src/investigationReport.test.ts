import { describe, expect, it } from 'vitest'
import { buildInvestigationReport } from './investigationReport'
import type { AnalyzeResponse } from './api/types'

const base: AnalyzeResponse = {
  overall_risk_score: 72, completeness_percentage: 60, checks: [{ check_name: 'payment_detection', status: 'fail', details: 'A payment was requested.' }],
  summary: 'Automated review result: high risk.', risk_band: 'high risk', risk_factors: [], reasons: [{ text: 'A payment was requested', impact: '+65' }],
  scoring_model: 'rule_based_v2', next_steps: ['Do not pay.'], complaint_summary: 'Summary text.', reportable_indicators: [],
  safety_actions: [{ id: 'report', title: 'Report it', steps: ['Call 1930.'], urgent: true, helpline: '1930', url: 'https://cybercrime.gov.in/' }],
}
const at = new Date('2026-11-21T00:00:00Z')

describe('investigation report', () => {
  it('contains the result, reasons, checks, safety steps and limits', () => {
    const text = buildInvestigationReport(base, at)
    for (const part of ['Generated: 2026-11-21T00:00:00.000Z', 'Outcome: high risk', '+65 A payment was requested', 'payment_detection: fail', 'Helpline: 1930', 'Do not pay.', 'not legal advice']) expect(text).toContain(part)
  })
  it('omits sections that have no content', () => {
    const text = buildInvestigationReport({ ...base, reasons: [], safety_actions: [], next_steps: [], complaint_summary: '' }, at)
    for (const part of ['## Why', '## Protect yourself', '## What to do next', '## Summary for a complaint']) expect(text).not.toContain(part)
  })
  it('never includes raw offer text or file names, even if present on the object', () => {
    const risky = { ...base, raw_text: 'SECRET OFFER BODY', filename: 'rahul-offer.pdf' } as unknown as AnalyzeResponse
    const text = buildInvestigationReport(risky, at)
    expect(text).not.toContain('SECRET OFFER BODY')
    expect(text).not.toContain('rahul-offer.pdf')
  })
})
