import { test, expect, type Page } from '@playwright/test'
import { loginAs } from './helpers'

/**
 * Guard UI phase 1 — the page half (spec §5.5, owner 2026-10-16). The backend half, including
 * the API refusing every non-admin command, is tests/backend/test_guard_ui_phase1.py.
 *
 *   TC-GU-08  Arm / Switch off: rendered for admin, absent for monitor_control and monitor
 *   TC-GU-12  admin: the list, playback in <video>, Correct / False alarm, the no-clip sentences;
 *             staff see neither the list nor the buttons
 *   TC-GU-13  the server unreachable: "Not measured", the last reading with its time in the
 *             sentence, no button
 *
 * All three failed on the page before the build (shown 2026-10-16): it had no button, no list,
 * and kept the last sentence on its own when the server could not be reached.
 */

function core(guard: Record<string, unknown>) {
  return {
    pedestals: [{
      pedestal_id: 1, cabinet_id: 'MAR_KRK_ORM_01', dock: 'A', reachable: true, smart_mode: true,
      berths: [], water_outlets: [],
      light: { on: false, scope: 'pedestal', available: false, unavailable_reason: 'read_only' },
      guard: { scope: 'pedestal', ...guard },
      alarm_count: 0,
    }],
  }
}

const CAMERA = {
  camera_id: 1, pedestal_id: 1, sentence: 'Guard on', sentence_code: 'on',
  desired_state: 'ARMED', state: 'ARMED', reason: null, auto_resumes: { used: 1, max: 2 },
}

const EVENTS = {
  total: 5, limit: 50, offset: 0,
  events: [
    { kind: 'person', id: 11, camera_id: 1, pedestal_id: 1, at_utc: '2026-10-16T19:14:00Z',
      label: null, has_frame: true, has_video: true, video_skipped: false, video_skip_reason: null },
    { kind: 'person', id: 10, camera_id: 1, pedestal_id: 1, at_utc: '2026-10-15T01:02:00Z',
      label: 'false_alarm', has_frame: true, has_video: true, video_skipped: false,
      video_skip_reason: null },
    { kind: 'person', id: 9, camera_id: 1, pedestal_id: 1, at_utc: '2026-10-14T01:02:00Z',
      label: null, has_frame: true, has_video: false, video_skipped: true,
      video_skip_reason: 'no_disk' },
    { kind: 'paused_cpu', id: 3, camera_id: 1, at_utc: '2026-10-13T08:00:00Z', reason: 'CPU' },
    { kind: 'unknown_state', id: 4, camera_id: 1, at_utc: '2026-10-12T08:00:00Z',
      reason: 'CALIBRATING' },
  ],
}

async function mockGuard(page: Page, opts: { guard?: Record<string, unknown> } = {}) {
  await page.route('**/api/marina/berths', (r) =>
    r.fulfill({ json: core(opts.guard ?? { state: 'on', sentence: 'Guard on',
                                            auto_resumes: { used: 1, max: 2 } }) }))
  await page.route('**/api/guard/status', (r) =>
    r.fulfill({ json: { marina_id: 'KRK', cameras: [CAMERA] } }))
  await page.route('**/api/guard/events?**', (r) => r.fulfill({ json: EVENTS }))
}

test('TC-GU-08 Arm / Switch off is rendered for admin only', async ({ page }) => {
  await loginAs(page, 'admin')
  await mockGuard(page)
  let sent = ''
  await page.route('**/api/guard/1/disable', (r) => { sent = r.request().url(); return r.fulfill({ status: 202, json: {} }) })
  await page.goto('/marina/guard')
  const button = page.getByTestId('guard-button')
  await expect(button).toHaveText('Switch off')
  await button.click()
  await expect(button).toHaveText('Sent')
  expect(sent).toContain('/api/guard/1/disable')
})

for (const role of ['monitor_control', 'monitor'] as const) {
  test(`TC-GU-08 no Arm / Switch off for ${role}`, async ({ page }) => {
    await loginAs(page, role as 'monitor')
    await mockGuard(page)
    await page.goto('/marina/guard')
    // The same pedestal, the same state — the sentence is there, the button is not.
    await expect(page.getByTestId('guard-sentence')).toHaveText(/Guard on/)
    // Not before the page has finished asking: the button would come from a second request, and
    // counting it at once passed a mutant that renders it for every role (2026-10-16).
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(500)
    await expect(page.getByTestId('guard-button')).toHaveCount(0)
    await expect(page.getByTestId('guard-events')).toHaveCount(0)
  })
}

test('TC-GU-12 admin plays a recording, labels it, and reads why a clip is missing', async ({ page }) => {
  await loginAs(page, 'admin')
  await mockGuard(page)
  await page.route('**/api/guard/events/11/video', (r) =>
    r.fulfill({ status: 200, contentType: 'video/mp4', body: Buffer.from('00000000') }))
  await page.route('**/api/guard/events/10/video', (r) =>
    r.fulfill({ status: 410, json: { detail: { reason: 'max_days', kind: 'video' } } }))
  let labelled: unknown = null
  await page.route('**/api/guard/events/11/label', (r) => {
    labelled = r.request().postDataJSON()
    return r.fulfill({ json: { status: 'labelled' } })
  })
  await page.goto('/marina/guard')

  const rows = page.getByTestId('guard-event-row')
  await expect(rows).toHaveCount(3)
  await expect(rows.nth(0)).toContainText('Person seen — needs checking')
  await expect(rows.nth(1)).toContainText('Person seen — marked false alarm')
  await expect(rows.nth(2)).toContainText('No recording — there was no space to record')
  const stateRows = page.getByTestId('guard-state-row')
  await expect(stateRows.nth(0)).toContainText('Guard paused — processor overloaded')
  // S7 (Q4b): a state we cannot read is shown raw, never as a resume or a pause.
  await expect(stateRows.nth(1)).toContainText('Guard reported a state we cannot read: CALIBRATING')

  await rows.nth(0).getByRole('button', { name: '▶ Play recording' }).click()
  await expect(page.getByTestId('guard-video')).toHaveCount(1)
  await rows.nth(1).getByRole('button', { name: '▶ Play recording' }).click()
  await expect(rows.nth(1)).toContainText('Recording deleted after 14 days')

  await rows.nth(0).getByRole('button', { name: 'False alarm' }).click()
  await expect.poll(() => labelled).toEqual({ label: 'false_alarm' })
  await expect(page.getByTestId('guard-resumes')).toHaveText('Automatic resumes left today: 1 of 2')
})

test('TC-GU-13 the server unreachable reads "Not measured", with the last reading and its time', async ({ page }) => {
  await loginAs(page, 'admin')
  await mockGuard(page)
  await page.clock.install()
  await page.goto('/marina/guard')
  await expect(page.getByTestId('guard-sentence')).toHaveText(/Guard on/)
  await expect(page.getByTestId('guard-button')).toHaveCount(1)

  // The next refresh (every 15 s) cannot reach the server.
  await page.unroute('**/api/marina/berths')
  await page.route('**/api/marina/berths', (r) => r.abort('connectionrefused'))
  await page.clock.runFor(16_000)
  await expect(page.getByTestId('guard-sentence')).toHaveText(/^\W*Not measured$/)
  await expect(page.getByTestId('guard-last-seen')).toHaveText(/^last seen \d\d:\d\d: Guard on$/)
  await expect(page.getByTestId('guard-button')).toHaveCount(0)
  await expect(page.getByTestId('guard-events')).toHaveCount(0)
})
