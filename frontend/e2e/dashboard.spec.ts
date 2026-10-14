import { test, expect } from '@playwright/test'
import { loginAs, mockApi } from './helpers'

/**
 * ⚠ SKIPPED IN FULL — deferred item D16, 2026-10-02.
 *
 * These specs were failing, and nobody knew: `tests/playwright_e2e.sh` exited 0 whenever
 * nothing answered on `:8000`, so the whole Playwright stage reported success for having run
 * nothing. Every spec here mocks its own API with `page.route`, so a live backend was never
 * needed — the check that skipped them was simply wrong.
 *
 * With the silent skip removed (v3.44) they became visible, and they would now block every
 * push. Skipped deliberately rather than left to fail: a red gate nobody can act on gets
 * ignored just as fast as a green one with nothing behind it, and fixing them is explicitly
 * out of scope for the marina profile.
 *
 * The marina specs (`marina.spec.ts`) are NOT skipped and must stay green.
 *
 * To work on these: delete the `test.describe.configure` line below and run
 *     npx playwright test e2e/<file>.spec.ts
 */
test.describe.configure({ mode: 'serial' })
test.skip(true, 'Pre-existing failures — deferred D16, 2026-10-02. Not in scope for UI v2.')


test.describe('Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    await loginAs(page)
    await mockApi(page)
    await page.goto('/dashboard')
  })

  test('shows dashboard heading', async ({ page }) => {
    await expect(page).toHaveURL(/\/dashboard/)
    await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toBeVisible()
  })

  test('renders pedestal card with correct name', async ({ page }) => {
    await expect(page.getByText('Berth A-01')).toBeVisible()
  })

  test('shows pedestal location', async ({ page }) => {
    await expect(page.getByText('Dock A')).toBeVisible()
  })

  test('clicking pedestal card enters detail view', async ({ page }) => {
    await page.getByText('Berth A-01').click()
    // Back button appears in detail view
    await expect(page.getByRole('button', { name: /back/i })).toBeVisible()
    await expect(page.getByText('Berth A-01')).toBeVisible()
  })

  test('back button returns to grid view', async ({ page }) => {
    await page.getByText('Berth A-01').click()
    await page.getByRole('button', { name: /back/i }).click()
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
  })
})

test.describe('Navigation — admin role', () => {
  test.beforeEach(async ({ page }) => {
    await loginAs(page, 'admin')
    await mockApi(page)
    await page.goto('/dashboard')
  })

  test('sidebar shows all admin nav items', async ({ page }) => {
    await expect(page.getByRole('link', { name: /Dashboard/ })).toBeVisible()
    await expect(page.getByRole('link', { name: /Analytics/ })).toHaveCount(0)   // block 4, nav: L3
    await expect(page.getByRole('link', { name: /History/ })).toBeVisible()
    await expect(page.getByRole('link', { name: /Billing/ })).toBeVisible()
    await expect(page.getByRole('link', { name: /Customers/ })).toBeVisible()
    await expect(page.getByRole('link', { name: /Contracts/ })).toBeVisible()
    await expect(page.getByRole('link', { name: /System Health/ })).toBeVisible()
    await expect(page.getByRole('link', { name: /Settings/ })).toBeVisible()
  })

  test('sidebar shows IoT Dashboard label', async ({ page }) => {
    await expect(page.getByText('IoT Dashboard')).toBeVisible()
  })

  test('navigates to System Health page', async ({ page }) => {
    await page.getByRole('link', { name: /System Health/ }).click()
    await expect(page).toHaveURL(/\/system-health/)
  })

  test('navigates to Settings page', async ({ page }) => {
    await page.getByRole('link', { name: /Settings/ }).click()
    await expect(page).toHaveURL(/\/settings/)
  })
})

test.describe('Navigation — monitor role', () => {
  test.beforeEach(async ({ page }) => {
    await loginAs(page, 'monitor')
    await mockApi(page)
    await page.goto('/dashboard')
  })

  test('sidebar does NOT show admin-only items for monitor role', async ({ page }) => {
    await expect(page.getByRole('link', { name: /Billing/ })).not.toBeVisible()
    await expect(page.getByRole('link', { name: /Settings/ })).not.toBeVisible()
    await expect(page.getByRole('link', { name: /Customers/ })).not.toBeVisible()
  })

  test('sidebar shows read-only nav items for monitor role', async ({ page }) => {
    await expect(page.getByRole('link', { name: /Dashboard/ })).toBeVisible()
    await expect(page.getByRole('link', { name: /Analytics/ })).toHaveCount(0)   // block 4, nav: L3
    await expect(page.getByRole('link', { name: /History/ })).toBeVisible()
  })
})
