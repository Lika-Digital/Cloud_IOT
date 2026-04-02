import { test, expect } from '@playwright/test'
import { loginAs, mockApi } from './helpers'

// Helper: navigate to the pedestal detail view
async function goToPedestalView(page: Parameters<typeof loginAs>[0]) {
  await loginAs(page)
  await mockApi(page)
  await page.goto('/dashboard')
  await page.getByText('Berth A-01').click()
  // Wait for PedestalView to render (pedestal image zone buttons appear)
  await expect(page.getByText('Quick Status')).toBeVisible()
}

test.describe('Sessions — Quick Status overview (PedestalView)', () => {
  test.beforeEach(async ({ page }) => {
    await goToPedestalView(page)
  })

  test('shows Quick Status section after entering pedestal view', async ({ page }) => {
    await expect(page.getByText('Quick Status')).toBeVisible()
  })

  test('active session shows socket and customer name in Quick Status', async ({ page }) => {
    // Fixture: active session on Socket 2 for "Test Sailor"
    // Use nth(1) to target the Quick Status span, not the sr-only label inside the zone button
    await expect(page.getByText('Socket 2').nth(1)).toBeVisible()
    await expect(page.getByText('Test Sailor')).toBeVisible()
  })

  test('active session shows Active badge in Quick Status', async ({ page }) => {
    // The AllSessionsOverview renders a badge-active span
    await expect(page.locator('.badge-active').first()).toBeVisible()
  })

  test('shows Legend section', async ({ page }) => {
    await expect(page.getByText('Legend')).toBeVisible()
  })
})

test.describe('Sessions — Socket detail panel', () => {
  test.beforeEach(async ({ page }) => {
    await goToPedestalView(page)
  })

  test('clicking active socket zone opens detail panel with Stop Session', async ({ page }) => {
    // Socket 2 is active (green ring) — click it via its sr-only label or the zone button
    // Zone buttons are overlaid on the pedestal image; Socket 2 is at top:'52%', left:'3%'
    // Use the tooltip text "Stop Session" visible on hover, or click the zone and check panel
    // The ZoneButton for an active socket shows tooltip "Stop Session"
    // We click it by its position relative to the pedestal image container
    const pedestalContainer = page.locator('.relative.inline-block')
    await expect(pedestalContainer).toBeVisible()

    // Buttons inside the container — Socket 2 is the 2nd left-side button
    const zoneButtons = pedestalContainer.locator('button')
    // Click the button that wraps Socket 2 (2nd button on left, active=green)
    // The active socket button has bg-green-500/30 styling
    const activeBtn = pedestalContainer.locator('button').filter({
      has: page.locator('.bg-green-500\\/30'),
    }).first()
    // Fall back: just click the button with the green ring class
    const btn = pedestalContainer.locator('button.bg-green-500\\/30, button[class*="bg-green-500"]').first()
    await btn.click()

    // SocketDetailPanel opens — shows "Stop Session" for admin
    await expect(page.getByRole('button', { name: 'Stop Session' })).toBeVisible()
  })

  test('Stop Session button calls stop endpoint and closes panel', async ({ page }) => {
    let stopCalled = false
    await page.route('**/api/controls/101/stop', route => {
      stopCalled = true
      return route.fulfill({
        json: { id: 101, pedestal_id: 1, socket_id: 2, type: 'electricity',
                status: 'completed', started_at: new Date().toISOString(),
                ended_at: new Date().toISOString(), energy_kwh: 1.23, water_liters: null,
                customer_id: 5, customer_name: 'Test Sailor', deny_reason: null },
      })
    })

    const pedestalContainer = page.locator('.relative.inline-block')
    const btn = pedestalContainer.locator('button[class*="bg-green-500"]').first()
    await btn.click()

    await page.getByRole('button', { name: 'Stop Session' }).click()
    expect(stopCalled).toBe(true)

    // After stop, session is completed — socket returns to idle
    await expect(page.getByRole('button', { name: 'Stop Session' })).not.toBeVisible()
  })
})

test.describe('Sessions — Pending session zone (socket panel)', () => {
  test.beforeEach(async ({ page }) => {
    await loginAs(page)
    // Override mocks to have a pending session on socket 3 instead of active
    await page.route('**/api/pedestals', route => route.fulfill({
      json: [{ id: 1, name: 'Berth A-01', location: 'Dock A',
               ip_address: '192.168.1.10', camera_ip: null,
               data_mode: 'real', initialized: true,
               mobile_enabled: true, ai_enabled: false }],
    }))
    await page.route('**/api/sessions/active', route => route.fulfill({ json: [] }))
    await page.route('**/api/sessions/pending', route => route.fulfill({
      json: [{
        id: 201, pedestal_id: 1, socket_id: 3, type: 'electricity',
        status: 'pending', started_at: new Date().toISOString(),
        ended_at: null, energy_kwh: null, water_liters: null,
        customer_id: 7, customer_name: 'Pending Sailor', deny_reason: null,
      }],
    }))
    await page.route('**/api/health', route => route.fulfill({ json: { status: 'ok', uptime: 3600 } }))
    await page.route('**/api/pedestals/health', route => route.fulfill({ json: {} }))
    await page.route('**/api/analytics**', route => route.fulfill({ json: [] }))
    await page.route('**/api/billing/**', route => route.fulfill({ json: {} }))
    await page.route('**/api/auth/users', route => route.fulfill({
      json: [{ id: 1, email: 'admin@test.local', role: 'admin', is_active: true }],
    }))
    await page.route('**/api/contracts/**', route => route.fulfill({ json: [] }))
    await page.route('**/api/chat/unread-count', route => route.fulfill({ json: { unread_customers: 0 } }))
    await page.route('**/api/system/errors**', route => route.fulfill({ json: { items: [], total: 0 } }))
    await page.route('**/ws**', route => route.abort())

    await page.goto('/dashboard')
    await page.getByText('Berth A-01').click()
    await expect(page.getByText('Quick Status')).toBeVisible()
  })

  test('pending socket zone shows amber pulse styling', async ({ page }) => {
    // The pending socket zone button has animate-pulse class
    const pedestalContainer = page.locator('.relative.inline-block')
    const pendingBtn = pedestalContainer.locator('button.animate-pulse').first()
    await expect(pendingBtn).toBeVisible()
  })

  test('clicking pending socket opens panel showing session starting', async ({ page }) => {
    const pedestalContainer = page.locator('.relative.inline-block')
    const pendingBtn = pedestalContainer.locator('button.animate-pulse').first()
    await pendingBtn.click()

    await expect(page.getByText('Session starting…')).toBeVisible()
  })

  test('pending panel shows customer name', async ({ page }) => {
    const pedestalContainer = page.locator('.relative.inline-block')
    const pendingBtn = pedestalContainer.locator('button.animate-pulse').first()
    await expect(pendingBtn).toBeVisible()
    await pendingBtn.click()

    await expect(page.getByText('Pending Sailor')).toBeVisible()
  })
})
