import { afterEach, describe, expect, it, vi } from 'vitest'
import { analyze, submitReport, withdrawReport, ApiError } from './client'

afterEach(() => vi.unstubAllGlobals())

const response = (status: number, detail: string) => ({
  ok: false,
  status,
  json: async () => ({ detail }),
}) as Response

describe('backend error translation', () => {
  it.each([
    [413, 'text too large', 'This file is over 10 MB. Upload a smaller file or paste the text instead.'],
    [415, 'unsupported type', "This file type isn't supported. Use PDF, PNG, JPG or .eml."],
    [422, 'no extracted text', "We couldn't read any text in this file. Try a clearer image or paste the text."],
    [429, 'rate limited', 'Too many checks in a minute. Wait a moment and try again.'],
  ])('shows the specified message for HTTP %i', async (status, detail, message) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(status, detail)))
    await expect(analyze('offer', null)).rejects.toThrow(message)
  })

  it.each([
    ['/report', 'report token expired or already used', 'This report token expired or was already used. Check the offer again to create a new report.'],
    ['/report', 'current consent is required', 'Consent is required. Review and select the consent checkbox before submitting the report.'],
    ['/report/withdraw', 'invalid or already-used withdrawal code', 'That withdrawal code is invalid or already used. Check the code you saved; a report can be withdrawn once.'],
  ])('explains what to do for %s errors', async (path, detail, message) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(400, detail)))
    const request = path === '/report'
      ? submitReport({ report_token: 'report-token-that-is-long-enough', consent: true, consent_version: 4, selected_indicators: [] })
      : withdrawReport({ code: 'withdrawal-code-that-is-long-enough' })
    await expect(request).rejects.toThrow(message)
  })

  it('reports server connection failure in the interface voice', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('connection refused')))
    await expect(analyze('offer', null)).rejects.toThrow("The server can't be reached. Check your connection and try again.")
    expect(new ApiError(0, 'example')).toBeInstanceOf(Error)
  })
})
