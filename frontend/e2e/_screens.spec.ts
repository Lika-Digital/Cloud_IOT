import { test, expect, type Page } from '@playwright/test'
import { loginAs } from './helpers'

/**
 * Screenshot harness — every marina screen at desktop AND phone width.
 *
 * Not part of the gate. Run deliberately:
 *     npx playwright test e2e/_screens.spec.ts
 *
 * Phone width is 380 px, which is where things actually break: the "IN USE" wrap that got
 * caught by eye at 1280 px would have been worse here, and "phone first" was a design rule
 * because staff read this walking the pier.
 *
 * Every screen is also asserted to have NO page-level horizontal scroll at phone width. A
 * screenshot alone would let a sideways-scrolling page look fine, because the capture is as
 * wide as the content rather than as wide as the phone.
 */

// 60 s, not the global 15 s. This harness is the FIRST thing to touch the dev server in
// a capture run, so it pays Vite's cold start — the first test timed out mid-click
// while the page was still settling. A capture tool waiting longer costs nothing; the
// gate specs keep the short timeout, where a slow page IS the signal.
test.describe.configure({ timeout: 60_000 })

const DESKTOP = { width: 1280, height: 900 }
const PHONE = { width: 380, height: 820 }
const DIR = '../tests/logs/local/screens'

function core() {
  return {
    pedestals: [{
      pedestal_id: 1, cabinet_id: 'MAR_KRK_ORM_01', dock: 'A',
      reachable: true, smart_mode: true,
      berths: [
        { berth_id: 101, berth_number: 1, status: 'ok', status_code: 'ok',
          status_sentence: null, status_rank: 9,
          power: { outlet: 'Q1', on: true, state: 'active', amps: 14.8, unit: 'A',
                   available: true, unavailable_reason: null },
          occupied: true, occupied_known: true, vessel_matches: true,
          vessel_match_configured: true, alarm_count: 0 },
        { berth_id: 102, berth_number: 2, status: 'ok', status_code: 'ok',
          status_sentence: null, status_rank: 9,
          power: { outlet: 'Q2', on: false, state: 'idle', amps: null, unit: 'A',
                   available: true, unavailable_reason: null },
          occupied: false, occupied_known: true, vessel_matches: null,
          vessel_match_configured: false, alarm_count: 0 },
        { berth_id: 103, berth_number: 3, status: 'attention', status_code: 'water_leak',
          status_sentence: 'Water leak detected', status_rank: 3,
          power: { outlet: 'Q3', on: true, state: 'active', amps: 5.4, unit: 'A',
                   available: true, unavailable_reason: null },
          occupied: true, occupied_known: true, vessel_matches: false,
          vessel_match_configured: true, alarm_count: 2 },
        { berth_id: 104, berth_number: 4, status: 'unknown', status_code: 'outlet_silent',
          status_sentence: 'This outlet has not reported recently', status_rank: 2.5,
          power: { outlet: 'Q4', on: false, state: 'unknown', amps: null, unit: 'A',
                   available: true, unavailable_reason: null },
          occupied: false, occupied_known: false, vessel_matches: null,
          vessel_match_configured: false, alarm_count: 0 },
      ],
      water_outlets: [
        { outlet: 'V1', on: true, state: 'active', litres_per_min: 12.4, unit: 'L/min',
          rated_liters_per_min: 20, in_use: true, available: true, unavailable_reason: null },
        { outlet: 'V2', on: false, state: 'unknown', litres_per_min: null, unit: 'L/min',
          rated_liters_per_min: 20, in_use: false, available: true, unavailable_reason: null },
      ],
      light: { on: true, scope: 'pedestal', available: true, unavailable_reason: null },
      guard: { state: 'on', sentence: 'Guard on', scope: 'pedestal' },
      alarm_count: 2,
    }],
  }
}

function berthDetail() {
  const b = core().pedestals[0].berths[2]
  return {
    ...b,
    pedestal_id: 1,
    cabinet_id: 'MAR_KRK_ORM_01',
    outlet_spec: {
      outlet: 'Q3', rated_amps: 16, phases: 1, meter_type: 'ABB D11 15-M 40',
    },
    consumption: { kwh: 34.812, source: 'register', note: 'Meter reading.' },
    reference_image: null,
    guard: { state: 'on', sentence: 'Guard on', scope: 'pedestal' },
    guard_scope_note:
      'Guard covers the whole pedestal, so these events may come from any berth it serves.',
  }
}

function alarms() {
  return {
    alarms: [
      { alarm_id: 9, pedestal_id: 1, cabinet_id: 'MAR_KRK_ORM_01',
        status_code: 'water_leak', sentence: 'Water leak detected', severity: 'critical',
        raised_at: '2026-10-03T06:12:00Z', resolved_at: null, active: true },
      { alarm_id: 8, pedestal_id: 1, cabinet_id: 'MAR_KRK_ORM_01',
        status_code: 'breaker_tripped', sentence: 'Power tripped — needs resetting',
        severity: 'warning', raised_at: '2026-10-03T05:40:00Z', resolved_at: null,
        active: true },
      { alarm_id: 7, pedestal_id: 1, cabinet_id: 'MAR_KRK_ORM_01',
        status_code: 'too_hot', sentence: 'Pedestal too hot', severity: 'warning',
        raised_at: '2026-10-02T14:03:00Z', resolved_at: '2026-10-02T15:10:00Z',
        active: false },
    ],
  }
}

async function mockAll(page: Page) {
  await page.route('**/api/marina/berths', (r) => r.fulfill({ json: core() }))
  await page.route('**/api/marina/berths/*', (r) => r.fulfill({ json: berthDetail() }))
  await page.route('**/api/marina/alarms', (r) => r.fulfill({ json: alarms() }))
  await page.route('**/api/marina/berth-assignments/*', (r) => r.fulfill({
    json: {
      pedestal_id: 1,
      assignments: [1, 2, 3, 4].map((n) => ({
        berth_id: 100 + n, socket_id: n,
        assigned_at: '2026-10-01T09:00:00Z', assigned_by: 'damir@lika.digital',
      })),
    },
  }))
  await page.route('**/api/nfc/outlets/*', (r) => r.fulfill({
    json: {
      cabinet_id: 'MAR_KRK_ORM_01', reported: true,
      outlets: [
        { outlet_name: 'Q1', outlet_type: 'socket', session_type: 'electricity',
          meter_type: 'ABB D13 15-M 65', phases: 3, rated_amps: 32,
          rated_liters_per_min: null, state: null, nfc_tag_id: null },
        { outlet_name: 'Q2', outlet_type: 'socket', session_type: 'electricity',
          meter_type: 'ABB D11 15-M 40', phases: 1, rated_amps: 32,
          rated_liters_per_min: null, state: null, nfc_tag_id: null },
        { outlet_name: 'Q3', outlet_type: 'socket', session_type: 'electricity',
          meter_type: 'ABB D11 15-M 40', phases: 1, rated_amps: 16,
          rated_liters_per_min: null, state: null, nfc_tag_id: null },
        { outlet_name: 'Q4', outlet_type: 'socket', session_type: 'electricity',
          meter_type: 'ABB D11 15-M 40', phases: 1, rated_amps: 16,
          rated_liters_per_min: null, state: null, nfc_tag_id: null },
      ],
    },
  }))
}

const SCREENS: { name: string; path: string; ready: string; after?: (p: Page) => Promise<void> }[] = [
  { name: '1-dashboard', path: '/marina', ready: 'marina-dashboard',
    after: async (p) => { await p.getByRole('button', { name: /^All/ }).click() } },
  { name: '2-berth-detail', path: '/marina/berth/103', ready: 'berth-detail' },
  { name: '3-water', path: '/marina/water', ready: 'marina-water' },
  { name: '4-alarms', path: '/marina/alarms', ready: 'marina-alarms' },
  { name: '5-guard', path: '/marina/guard', ready: 'marina-guard' },
  { name: '6-setup', path: '/marina/setup/1', ready: 'marina-setup',
    after: async (p) => { await p.getByRole('button', { name: 'Next' }).click() } },
]

for (const s of SCREENS) {
  for (const [label, size] of [['desktop', DESKTOP], ['phone', PHONE]] as const) {
    test(`capture ${s.name} ${label}`, async ({ page }) => {
      await loginAs(page, 'monitor')
      await mockAll(page)
      await page.setViewportSize(size)
      await page.goto(s.path)
      await page.getByTestId(s.ready).waitFor()
      if (s.after) await s.after(page)
      await page.waitForTimeout(300)
      await page.screenshot({ path: `${DIR}/${s.name}-${label}.png`, fullPage: true })

      if (label === 'phone') {
        // A screenshot cannot show this: fullPage captures as wide as the CONTENT, so a page
        // that scrolls sideways on a real phone looks perfectly fine in the image.
        const overflow = await page.evaluate(() =>
          document.documentElement.scrollWidth - document.documentElement.clientWidth)
        expect(overflow, `${s.name} scrolls ${overflow}px sideways at 380px`).toBeLessThanOrEqual(1)
      }
    })
  }
}
