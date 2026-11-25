import { expect, test } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const capture = (page: import('@playwright/test').Page, testInfo: import('@playwright/test').TestInfo, name: string, fullPage = false) => {
  const dir = path.join(root, 'docs', 'screenshots')
  mkdirSync(dir, { recursive: true })
  return page.screenshot({ path: path.join(dir, `${name}-${testInfo.project.name}.png`), animations: 'disabled', fullPage })
}

test('demo analysis, reporting, dashboard, and public screens', async ({ page }, testInfo) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Check an offer before you pay anything.' })).toBeVisible()
  await capture(page, testInfo, 'home')
  await expect(page.getByText('Try a sample:')).toBeVisible()

  const samples = [
    { button: 'Emberlake offer', key: 'legit_emberlake.txt', band: 'Likely legitimate', shot: 'sample-emberlake-result' },
    { button: 'Brightpath internship', key: 'legit_brightpath_young_startup.txt', band: 'Insufficient evidence', shot: 'sample-brightpath-result' },
    { button: 'Government scheme', key: 'scam_fake_govt_scheme_fee.txt', band: 'High risk', shot: 'result' },
    // Synthetic company-register cases (fictional companies; backend runs with the synthetic snapshot in DEMO_MODE).
    { button: 'Quillmere internship', key: 'registry_name_match_quillmere.txt', band: 'Likely legitimate', shot: 'sample-quillmere-result' },
    { button: 'Tarnwick internship', key: 'registry_struck_off_tarnwick.txt', band: 'Insufficient evidence', shot: 'sample-tarnwick-result' },
    { button: 'Halvorn internship', key: 'registry_cin_mismatch_halvorn.txt', band: 'Insufficient evidence', shot: 'sample-halvorn-result' },
    // Shares a simulated sender (careerdesk.fees@ybl); reported below, then seen on the scam-trends page.
    { button: 'Corvane internship', key: 'scam_shared_upi_corvane.txt', band: 'High risk', shot: 'sample-corvane-result' },
  ]
  for (const [index, sample] of samples.entries()) {
    if (index > 0) await page.getByRole('button', { name: 'Check another offer' }).click()
    await page.getByRole('button', { name: sample.button }).click()
    await expect(page.getByLabel('Paste offer text')).not.toHaveValue('')
    await expect(page.getByText(`Sample loaded: ${sample.key.replace('.txt', '')}`)).toBeVisible()
    await page.getByRole('button', { name: 'Check offer' }).click()
    await expect(page.getByRole('heading', { name: sample.band, exact: true })).toBeVisible()
    if (sample.band === 'Likely legitimate') await expect(page.getByRole('button', { name: 'Share a suspected scam' })).toHaveCount(0)
    if (sample.button === 'Corvane internship') await expect(page.getByRole('table', { name: 'Why' }).getByText('Reported in 3+ separate reports')).toBeVisible()
    await capture(page, testInfo, sample.shot)
  }

  await page.getByRole('button', { name: 'Share a suspected scam' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('heading', { name: 'Choose details to share' })).toBeVisible()
  await capture(page, testInfo, 'report-details')
  const selections = dialog.locator('fieldset input[type="checkbox"]')
  const count = await selections.count()
  if (count > 1) await selections.first().uncheck()
  await dialog.getByRole('button', { name: 'Continue' }).click()
  await expect(dialog.getByRole('heading', { name: 'Review and consent' })).toBeVisible()
  await capture(page, testInfo, 'report-consent')
  const consent = dialog.getByRole('checkbox', { name: /Share these details to warn other job seekers/ })
  await consent.check()
  await dialog.getByRole('button', { name: 'Report scam' }).click()
  await expect(dialog.getByRole('heading', { name: 'Reported' })).toBeVisible()
  const codeText = await dialog.locator('[class*="withdrawCode"] strong').innerText()
  await expect(codeText.length).toBeGreaterThan(0)
  await expect(dialog.getByText('Save this code. It’s the only way to withdraw this report, and we can’t show it again.')).toBeVisible()
  expect(await page.evaluate(() => [localStorage.length, sessionStorage.length])).toEqual([0, 0])
  await capture(page, testInfo, 'report-success')

  await page.goto('/withdraw')
  await expect(page.getByRole('heading', { name: 'Withdraw a report' })).toBeVisible()
  await capture(page, testInfo, 'withdraw')
  await page.getByLabel('Withdrawal code').fill(codeText)
  await page.getByRole('button', { name: 'Withdraw report' }).click()
  await expect(page.getByRole('status')).toHaveText('Withdrawn. Your report no longer counts towards any warning.')
  await capture(page, testInfo, 'withdraw-success')

  await page.goto('/dispute')
  await expect(page.getByRole('heading', { name: 'Dispute an indicator' })).toBeVisible()
  await page.getByLabel('Indicator value').fill('suspect.example')
  await page.getByLabel('Contact email').fill('legal@suspect.example')
  await page.getByLabel('Reason').selectOption('our_business_detail')
  await capture(page, testInfo, 'dispute')
  await page.getByRole('button', { name: 'Submit dispute' }).click()
  await expect(page.getByRole('status')).toContainText('Dispute recorded; scoring continues while it is under review.')
  await capture(page, testInfo, 'dispute-success')

  await page.goto('/dashboard')
  await expect(page.getByRole('heading', { name: 'Scam trends' })).toBeVisible()
  const senders = page.getByRole('table', { name: 'Reported senders' })
  await expect(senders).toBeVisible()
  await expect(page.getByText('Shown only after 3 or more separate reports name the same sender, made on at least two different days.')).toBeVisible()
  // The sender the student just checked (Corvane letter) is on the warning list, masked.
  await expect(senders.getByRole('rowheader', { name: 'careerd•••@ybl' })).toBeVisible()
  await expect(senders.getByText('Disputed by the company, under review')).toBeVisible()
  await expect(senders.getByText(/talentbridge-jobs\.example/)).toHaveCount(0)   // only 2 reports: never shown
  await expect(page.getByRole('heading', { name: 'Results by week' })).toBeVisible()
  await expect(page.getByRole('table', { name: 'Scam categories', exact: true })).toBeVisible()
  // Full page, so the senders table, the 12-week chart and the category table are all in the image.
  await capture(page, testInfo, 'dashboard', true)
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('link', { name: 'Export warning list' }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toBe('scam-warning-list.csv')

  await page.goto('/how-it-works')
  await expect(page.getByRole('heading', { name: 'What this checks' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Read the privacy design' })).toBeVisible()
  await capture(page, testInfo, 'how-it-works')
})
