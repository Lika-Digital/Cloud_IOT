import { test, expect } from '@playwright/test'
import { loginAs, mockApi } from './helpers'

test.describe('Sessions — active session display', () => {
  test.beforeEach(async ({ page }) => {
    await loginAs(page)
    await mockApi(page)
    await page.goto('/dashboard')
    // Enter pedestal detail view
    await page.getByText('Berth A-01').click()
  })

  test('shows active sessions section', async ({ page }) => {
    // Active session from fixture: session #101, Socket 2
    await expect(page.getByText(/Active Sessions/)).toBeVisible()
  })

  test('shows active session card with socket info', async ({ page }) => {
    await expect(page.getByText('Socket 2')).toBeVisible()
  })

  test('active session card shows customer name', async ({ page }) => {
    await expect(page.getByText('Test Sailor')).toBeVisible()
  })

  test('shows Stop button on active session', async ({ page }) => {
    await expect(page.getByRole('button', { name: /stop/i })).toBeVisible()
  })
})

test.describe('Sessions — pending approvals', () => {
  test.beforeEach(async ({ page }) => {
    await loginAs(page)
    // Override the pending sessions mock to return a pending session
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
    await page.route('**/api/chat/unread-count', route => route.fulfill({ json: { count: 0 } }))
    await page.route('**/api/system/errors**', route => route.fulfill({ json: { items: [], total: 0 } }))
    await page.route('**/ws**', route => route.abort())

    await page.goto('/dashboard')
    await page.getByText('Berth A-01').click()
  })

  test('shows pending approvals section', async ({ page }) => {
    await expect(page.getByText(/Pending Approvals/)).toBeVisible()
  })

  test('shows pending session with customer name', async ({ page }) => {
    await expect(page.getByText('Pending Sailor')).toBeVisible()
  })

  test('Allow and Deny buttons are visible', async ({ page }) => {
    await expect(page.getByRole('button', { name: 'Allow' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Deny' })).toBeVisible()
  })

  test('clicking Allow calls allow endpoint and removes pending card', async ({ page }) => {
    let allowCalled = false
    await page.route('**/api/sessions/201/allow', route => {
      allowCalled = true
      return route.fulfill({
        json: { id: 201, pedestal_id: 1, socket_id: 3, type: 'electricity',
                status: 'active', started_at: new Date().toISOString(),
                ended_at: null, energy_kwh: 0, water_liters: null,
                customer_id: 7, customer_name: 'Pending Sailor', deny_reason: null },
      })
    })

    await page.getByRole('button', { name: 'Allow' }).click()
    expect(allowCalled).toBe(true)
    // Pending section disappears when no pending sessions remain
    await expect(page.getByText(/Pending Approvals/)).not.toBeVisible()
  })

  test('clicking Deny opens deny dialog', async ({ page }) => {
    await page.getByRole('button', { name: 'Deny' }).click()
    // DenyDialog renders with a reason textarea or input
    await expect(page.getByText(/deny/i)).toBeVisible()
  })
})

test.describe('Sessions — stop active session', () => {
  test.beforeEach(async ({ page }) => {
    await loginAs(page)
    await mockApi(page)
    await page.goto('/dashboard')
    await page.getByText('Berth A-01').click()
  })

  test('clicking Stop calls stop endpoint and removes session', async ({ page }) => {
    let stopCalled = false
    await page.route('**/api/sessions/101/stop', route => {
      stopCalled = true
      return route.fulfill({
        json: { id: 101, pedestal_id: 1, socket_id: 2, type: 'electricity',
                status: 'completed', started_at: new Date().toISOString(),
                ended_at: new Date().toISOString(), energy_kwh: 1.23, water_liters: null,
                customer_id: 5, customer_name: 'Test Sailor', deny_reason: null },
      })
    })

    await page.getByRole('button', { name: /stop/i }).click()
    expect(stopCalled).toBe(true)
    await expect(page.getByText(/Active Sessions/)).not.toBeVisible()
  })
})
