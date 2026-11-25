import { expect, test } from '@playwright/test'

// Fictional offer: .example domain, made-up UPI handle. It asks for a fee, which always means "High risk".
const SCAM = `Dear candidate, you are selected for the Quillmere Trainee role at Quillmere Labs.
Pay a refundable registration fee of Rs 2,500 to UPI fees.desk@ybl within 24 hours to confirm your seat.
Reply to hr@quillmere-careers.example.`

test('check an offer, report it, withdraw, dispute, and public pages', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Check an offer before you pay anything.' })).toBeVisible()
  await expect(page.getByText('Try a sample:')).toHaveCount(0)            // no sample buttons outside a demo build
  await expect(page.getByText(/Choose up to 5 files \(PDF, image or \.txt\), or one \.eml/)).toBeVisible()

  await page.getByLabel('Paste offer text').fill(SCAM)
  await page.getByRole('button', { name: 'Check offer' }).click()
  await expect(page.getByRole('heading', { name: 'High risk', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Report it to the police' })).toBeVisible()

  await page.getByRole('button', { name: 'Share a suspected scam' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('heading', { name: 'Choose details to share' })).toBeVisible()
  await dialog.getByRole('button', { name: 'Continue' }).click()
  await expect(dialog.getByRole('heading', { name: 'Review and consent' })).toBeVisible()
  await dialog.getByRole('checkbox', { name: /Share these details to warn other job seekers/ }).check()
  await dialog.getByRole('button', { name: 'Report scam' }).click()
  await expect(dialog.getByRole('heading', { name: 'Reported' })).toBeVisible()
  const code = await dialog.locator('[class*="withdrawCode"] strong').innerText()
  expect(code.length).toBeGreaterThan(0)
  expect(await page.evaluate(() => [localStorage.length, sessionStorage.length])).toEqual([0, 0])

  await page.goto('/withdraw')
  await page.getByLabel('Withdrawal code').fill(code)
  await page.getByRole('button', { name: 'Withdraw report' }).click()
  await expect(page.getByRole('status')).toHaveText('Withdrawn. Your report no longer counts towards any warning.')

  await page.goto('/dispute')
  await expect(page.getByRole('heading', { name: 'Dispute an indicator' })).toBeVisible()
  await page.getByLabel('Indicator value').fill('suspect.example')
  await page.getByLabel('Contact email').fill('legal@suspect.example')
  await page.getByLabel('Reason').selectOption('our_business_detail')
  await page.getByRole('button', { name: 'Submit dispute' }).click()
  await expect(page.getByRole('status')).toContainText('Dispute recorded; scoring continues while it is under review.')

  // A fresh database has no senders with 3+ separate reports on 2+ days, so none may be listed.
  await page.goto('/dashboard')
  await expect(page.getByRole('heading', { name: 'Scam trends' })).toBeVisible()
  await expect(page.getByText(/or more separate reports/).first()).toBeVisible()
  await expect(page.getByText(/fees\.desk/)).toHaveCount(0)

  await page.goto('/verify-dispute')
  await expect(page.getByText(/needs the link from the verification email/)).toBeVisible()

  await page.goto('/how-it-works')
  await expect(page.getByRole('heading', { name: 'What this checks' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Read the privacy design' })).toBeVisible()
})

test('an .eml mixed with other files is explained before anything is sent', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel(/Choose up to 5 files/).setInputFiles([
    { name: 'a.eml', mimeType: 'message/rfc822', buffer: Buffer.from('Subject: x\n\nbody') },
    { name: 'b.txt', mimeType: 'text/plain', buffer: Buffer.from('hello') },
  ])
  await expect(page.getByText(/must be uploaded on its own/)).toBeVisible()
})

test('security headers are sent by the app server', async ({ request }) => {
  const r = await request.get('http://127.0.0.1:8000/health')
  expect(r.headers()['x-content-type-options']).toBe('nosniff')
  expect(r.headers()['content-security-policy']).toContain("default-src 'none'")
})
