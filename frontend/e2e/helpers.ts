import { Page } from '@playwright/test'

/** Inject a valid JWT into localStorage so the app thinks we're logged in. */
export async function loginAs(page: Page, role: 'admin' | 'monitor' = 'admin') {
  // Real JWT structure: header.payload.signature
  // Payload: { sub: "1", email: "admin@test.local", role: "admin", exp: far future }
  const payload = btoa(JSON.stringify({
    sub: '1',
    email: 'admin@test.local',
    role,
    exp: Math.floor(Date.now() / 1000) + 86400 * 365,
  }))
  const fakeJwt = `eyJhbGciOiJIUzI1NiJ9.${payload}.fake_sig`

  await page.addInitScript((args) => {
    // Zustand persist key for authStore
    localStorage.setItem('auth-store', JSON.stringify({
      state: {
        token: args.jwt,
        role: args.role,
        email: 'admin@test.local',
        isAuthenticated: true,
      },
      version: 0,
    }))
  }, { jwt: fakeJwt, role })
}

/** Mock all common API endpoints with realistic fixture data. */
export async function mockApi(page: Page) {
  // Pedestals
  await page.route('**/api/pedestals', route => route.fulfill({
    json: [{
      id: 1, name: 'Berth A-01', location: 'Dock A',
      ip_address: '192.168.1.10', camera_ip: null,
      data_mode: 'real', initialized: true,
      mobile_enabled: true, ai_enabled: false,
    }],
  }))

  // Active + pending sessions
  await page.route('**/api/sessions/active', route => route.fulfill({
    json: [{
      id: 101, pedestal_id: 1, socket_id: 2, type: 'electricity',
      status: 'active', started_at: new Date().toISOString(),
      ended_at: null, energy_kwh: 1.23, water_liters: null,
      customer_id: 5, customer_name: 'Test Sailor', deny_reason: null,
    }],
  }))
  await page.route('**/api/sessions/pending', route => route.fulfill({ json: [] }))

  // System health
  await page.route('**/api/health', route => route.fulfill({
    json: { status: 'ok', uptime: 3600 },
  }))

  // Pedestal health (now requires auth)
  await page.route('**/api/pedestals/health', route => route.fulfill({
    json: { '1': { opta_connected: true, last_heartbeat: new Date().toISOString(),
                   camera_reachable: false, last_camera_check: null,
                   temp_sensor_reachable: false, last_temp_sensor_check: null } },
  }))

  // Analytics
  await page.route('**/api/analytics**', route => route.fulfill({ json: [] }))

  // Billing
  await page.route('**/api/billing/**', route => route.fulfill({ json: {} }))

  // Users
  await page.route('**/api/auth/users', route => route.fulfill({
    json: [{ id: 1, email: 'admin@test.local', role: 'admin', is_active: true }],
  }))

  // Contracts
  await page.route('**/api/contracts/**', route => route.fulfill({ json: [] }))

  // Chat unread
  await page.route('**/api/chat/unread-count', route => route.fulfill({ json: { unread_customers: 0 } }))

  // Error logs
  await page.route('**/api/system/errors**', route => route.fulfill({ json: { items: [], total: 0 } }))

  // WebSocket — intercept and do nothing (avoids connection errors)
  await page.route('**/ws**', route => route.abort())
}
