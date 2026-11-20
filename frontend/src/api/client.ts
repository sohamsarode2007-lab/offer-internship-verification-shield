import type { AnalyzeResponse, DisputeRequest, DisputeResponse, InstitutionDashboard, ReportRequest, ReportResponse, WithdrawRequest, WithdrawResponse } from './types'

const API_BASE = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) { super(message) }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, init)
  } catch {
    throw new ApiError(0, "The server can't be reached. Check your connection and try again.")
  }
  if (!response.ok) {
    const messages: Record<number, string> = {
      413: 'This file is over 10 MB. Upload a smaller file or paste the text instead.',
      415: "This file type isn't supported. Use PDF, PNG, JPG, BMP, TIFF, .eml or .txt.",
      422: "We couldn't read any text in this file. Try a clearer image or paste the text.",
      429: 'Too many checks in a minute. Wait a moment and try again.',
    }
    let detail = ''
    try {
      const body = await response.json()
      detail = typeof body.detail === 'string' ? body.detail : ''
    } catch { /* The status message is enough. */ }
    let message = messages[response.status] ?? (detail || 'The request failed. Try again.')
    // 413 covers both "file too big" and "text too long"; keep the server's wording for the text case.
    if (response.status === 413 && /characters/i.test(detail)) message = detail
    if (response.status === 400 && detail) {
      const lower = detail.toLowerCase()
      if (path === '/report' && (lower.includes('expired') || lower.includes('already used') || lower.includes('invalid report token'))) {
        message = 'This report token expired or was already used. Check the offer again to create a new report.'
      } else if (path === '/report' && lower.includes('consent')) {
        message = 'Consent is required. Review and select the consent checkbox before submitting the report.'
      } else if (path === '/report' && lower.includes('selected indicators')) {
        message = 'The selected details do not match this analysis. Start a new check and choose from the masked details shown.'
      } else if (path === '/report/withdraw') {
        message = 'That withdrawal code is invalid or already used. Check the code you saved; a report can be withdrawn once.'
      } else if (path === '/disputes') {
        message = 'The dispute could not be accepted. Check the indicator type, value, contact email and reason.'
      }
    }
    throw new ApiError(response.status, message)
  }
  return response.json() as Promise<T>
}

/** One file goes as "file"; several (up to 5) go as repeated "files" fields. */
export function analyze(text: string, file: File | File[] | null, linkLookups = false) {
  const body = new FormData()
  if (text.trim()) body.set('text', text)
  if (Array.isArray(file)) file.forEach(f => body.append('files', f))
  else if (file) body.set('file', file)
  if (linkLookups) body.set('link_lookups', 'true')
  return request<AnalyzeResponse>('/analyze', { method: 'POST', body })
}

export function submitReport(payload: ReportRequest) {
  return request<ReportResponse>('/report', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
}
export function withdrawReport(payload: WithdrawRequest) {
  return request<WithdrawResponse>('/report/withdraw', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
}
export function submitDispute(payload: DisputeRequest) {
  return request<DisputeResponse>('/disputes', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
}
export function loadDashboard() {
  return request<InstitutionDashboard>('/trends/dashboard')
}
export const SENDERS_CSV_URL = `${API_BASE}/trends/senders.csv`
export const WEEKLY_CSV_URL = `${API_BASE}/trends/weekly.csv`

/** Which optional features the server has switched on. Any failure means none. */
export async function loadConfig(): Promise<{ link_lookups: boolean }> {
  try { const data = await request<{ link_lookups?: boolean }>('/config'); return { link_lookups: data.link_lookups === true } }
  catch { return { link_lookups: false } }
}
