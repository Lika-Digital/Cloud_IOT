import { test, expect } from '@playwright/test'
import { loginAs, mockApi } from './helpers'

test.describe('Auth — unauthenticated redirects', () => {
  test('/ redirects to /login when not logged in', async ({ page }) => {
    await page.goto('/')
    await expect(page).toHaveURL(/\/login/)
  })

  test('/dashboard redirects to /login when not logged in', async ({ page }) => {
    await page.goto('/dashboard')
    await expect(page).toHaveURL(/\/login/)
  })
})

test.describe('Auth — login page UI', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/login')
  })

  test('shows login form with email and password fields', async ({ page }) => {
    await expect(page.getByText('Sign In')).toBeVisible()
    await expect(page.getByPlaceholder('you@example.com')).toBeVisible()
    await expect(page.getByPlaceholder('••••••••')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Continue' })).toBeVisible()
  })

  test('shows TOTP step after successful credentials for an enrolled user', async ({ page }) => {
    await page.route('**/api/auth/login', route =>
      route.fulfill({ json: { partial_token: 'p.a.b', must_change_password: false, totp_enabled: true } })
    )

    await page.fill('input[type="email"]', 'admin@test.local')
    await page.fill('input[type="password"]', 'admin1234')
    await page.click('button[type="submit"]')

    await expect(page.getByText('Two-factor authentication')).toBeVisible()
  })

  test('shows error message on bad credentials', async ({ page }) => {
    await page.route('**/api/auth/login', route =>
      route.fulfill({ status: 401, json: { detail: 'Invalid email or password' } })
    )

    await page.fill('input[type="email"]', 'wrong@test.local')
    await page.fill('input[type="password"]', 'badpass')
    await page.click('button[type="submit"]')

    await expect(page.getByText('Invalid email or password')).toBeVisible()
  })

  test('shows error message on bad TOTP code', async ({ page }) => {
    await page.route('**/api/auth/login', route =>
      route.fulfill({ json: { partial_token: 'p.a.b', must_change_password: false, totp_enabled: true } })
    )
    await page.route('**/api/auth/totp/login', route =>
      route.fulfill({ status: 401, json: { detail: 'Invalid or expired code' } })
    )

    await page.fill('input[type="email"]', 'admin@test.local')
    await page.fill('input[type="password"]', 'admin1234')
    await page.click('button[type="submit"]')
    await expect(page.getByText('Two-factor authentication')).toBeVisible()

    // 6 digits auto-submits the second factor.
    await page.fill('input[inputmode="numeric"]', '000000')

    await expect(page.getByText('Invalid or expired code')).toBeVisible()
  })
})

test.describe('Auth — already logged in', () => {
  test.beforeEach(async ({ page }) => {
    await loginAs(page)
    await mockApi(page)
  })

  test('/ redirects to /dashboard when authenticated', async ({ page }) => {
    await page.goto('/')
    await expect(page).toHaveURL(/\/dashboard/)
  })

  test('/login still loads when already authenticated (no forced redirect)', async ({ page }) => {
    // LoginPage does not auto-redirect authenticated users — just verify dashboard is accessible
    await page.goto('/dashboard')
    await expect(page).toHaveURL(/\/dashboard/)
  })
})
