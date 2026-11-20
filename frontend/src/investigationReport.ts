import type { AnalyzeResponse } from './api/types'

/**
 * Builds the downloadable investigation report entirely in the browser from the result already on screen.
 * Nothing is sent anywhere or stored. It never contains the offer text, uploaded file names or a file's contents.
 */
export function buildInvestigationReport(result: AnalyzeResponse, generatedAt: Date = new Date()): string {
  const lines: string[] = []
  const add = (...rows: string[]) => lines.push(...rows)
  const list = (items: string[]) => items.forEach(i => add(`- ${i}`))
  const clean = (value: string) => value.replace(/\s+/g, ' ').trim()

  add('# Offer check: investigation report', '',
    `Generated: ${generatedAt.toISOString()}`,
    `Method: ${result.scoring_model ?? 'rule-based checks'} (no AI model decides the result)`, '')
  if (result.company_name?.trim()) add(`Company named in the offer: ${clean(result.company_name)}`, '')

  add('## Result', '',
    `- Outcome: ${result.risk_band ?? 'not available'}`,
    `- Risk score: ${result.overall_risk_score} / 100`,
    `- Information completeness: ${result.completeness_percentage}%`, '',
    clean(result.summary), '')

  if (result.reasons?.length) { add('## Why', ''); list(result.reasons.map(r => `${r.impact ? `${r.impact} ` : ''}${clean(r.text)}`)); add('') }

  if (result.checks?.length) {
    add('## Checks', '')
    result.checks.forEach(c => add(`- ${c.check_name}: ${c.status}${c.details ? ` - ${clean(c.details)}` : ''}`))
    add('')
  }

  if (result.evidence_meta?.length) {
    add('## Where each check comes from', '')
    list(result.evidence_meta.map(m => `${m.check_name}: source ${m.source}; effect on score: ${m.affects}; confidence ${m.confidence}; freshness ${m.freshness}; rule version ${m.rule_version}; checked ${m.checked_at}`))
    add('')
  }

  if (result.safety_actions?.length) {
    add('## Protect yourself', '')
    result.safety_actions.forEach(a => { add(`### ${a.title}`); list(a.steps); if (a.helpline) add(`- Helpline: ${a.helpline}`); if (a.url) add(`- Portal: ${a.url}`); add('') })
  }

  if (result.self_checks?.length) {
    add('## Checks you can run yourself', '')
    result.self_checks.forEach(s => { add(`### ${s.title}`, `Number: ${s.number}`, `Page: ${s.url}`, clean(s.why)); list(s.steps); add('') })
  }

  if (result.next_steps?.length) { add('## What to do next', ''); list(result.next_steps); add('') }
  if (result.complaint_summary?.trim()) add('## Summary for a complaint', '', clean(result.complaint_summary), '')

  add('## Limits', '',
    'This is an automated, rule-based review of the text and files you submitted. It is not legal advice, not a police finding and not proof that an offer is genuine or fake.',
    'It does not include the offer text or any uploaded file.')
  return lines.join('\n') + '\n'
}
