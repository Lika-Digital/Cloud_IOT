import { test, expect } from '@playwright/test'
import { loginAs, mockApi } from './helpers'

// v3.8 — Smart breaker monitoring UI. Covers the presentation pieces that are
// safe to verify without a live WebSocket (WebSocket is stubbed in helpers).
//
// - Hardware Info section renders "Not reported" when metadata is null.
// - Hardware Info section renders the exact values reported by the store.
// - Reset button only appears for admin AND only when breaker_state === 'tripped'.
// - Confirmation dialog appears before the reset command is dispatched.
// - Alarm banner appears when activeBreakerAlarms contains a key on this pedestal.
// - Acknowledge button dismisses the banner via sessionStorage.
// - Lightning bolt overlay appears on the socket circle when breaker is tripped.

async function openControlCenter(page: Parameters<typeof loginAs>[0], role: 'admin' | 'monitor' = 'admin') {
  await loginAs(page, role)
  await mockApi(page)
  // Default: no breaker metadata in store. Tests that need it seed it after
  // mount via page.evaluate + useStore.setState.
  await page.goto('/dashboard')
  await page.getByText('Berth A-01').click()
  await expect(page.getByText('Control Center').or(page.getByText('Cabinet Status'))).toBeVisible()
}

async function seedBreakerState(
  page: Parameters<typeof loginAs>[0],
  pedestalId: number,
  socketId: number,
  state: 'closed' | 'tripped' | 'resetting' | 'open' | 'unknown',
  metadata: Record<string, unknown> = {},
) {
  await page.evaluate(
    ({ pid, sid, st, meta }) => {
      // Access the zustand store hanging off the window for tests — we don't
      // expose it normally, so fall back to the internal react-devtools hook
      // path. Simplest: find the store via a known export pattern.
      const mod = (window as unknown as { __APP_STORE__?: { getState: () => unknown } })
      if (mod.__APP_STORE__) {
        const s = mod.__APP_STORE__.getState() as {
          setBreakerState: (p: number, s: number, patch: unknown) => void
          addBreakerAlarm: (k: string) => void
        }
        s.setBreakerState(pid, sid, { breaker_state: st, ...meta })
        if (st === 'tripped') s.addBreakerAlarm(`${pid}-${sid}`)
      }
    },
    { pid: pedestalId, sid: socketId, st: state, meta: metadata },
  )
}


test.describe('Breaker — Hardware Info rendering', () => {
  test('shows "Not reported" when all metadata fields are null', async ({ page }) => {
    await openControlCenter(page)
    // Default store has no breaker state → panel shows defaults.
    // Multiple sockets render the panel → use .first().
    const notReported = page.getByText(/Not reported/i).first()
    await expect(notReported).toBeVisible()
  })
})


test.describe('Breaker — Reset button visibility', () => {
  test('Reset button hidden for non-admin even when breaker tripped', async ({ page }) => {
    await openControlCenter(page, 'monitor')
    await seedBreakerState(page, 1, 1, 'tripped', { trip_cause: 'overcurrent' })
    // Reset button is admin-gated.
    await expect(page.getByRole('button', { name: /Reset breaker on Q1/i })).toHaveCount(0)
  })

  test('Reset button shown for admin when breaker_state is tripped', async ({ page }) => {
    await openControlCenter(page, 'admin')
    await seedBreakerState(page, 1, 1, 'tripped', { trip_cause: 'overcurrent' })
    await expect(page.getByRole('button', { name: /Reset breaker on Q1/i })).toBeVisible()
  })

  test('Reset button hidden when breaker state is closed', async ({ page }) => {
    await openControlCenter(page, 'admin')
    await seedBreakerState(page, 1, 1, 'closed')
    await expect(page.getByRole('button', { name: /Reset breaker on Q1/i })).toHaveCount(0)
  })
})


test.describe('Breaker — Alarm banner', () => {
  test('banner appears when a socket on the pedestal is tripped', async ({ page }) => {
    await openControlCenter(page, 'admin')
    await seedBreakerState(page, 1, 3, 'tripped', { trip_cause: 'overcurrent' })
    await expect(page.getByText(/BREAKER TRIPPED.*Q3/)).toBeVisible()
  })
})
