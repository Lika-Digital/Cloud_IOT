import { test, expect } from '@playwright/test'
import { loginAs, mockApi } from './helpers'

test.describe('Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    await loginAs(page)
    await mockApi(page)
    await page.goto('/dashboard')
  })

  test('shows dashboard heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
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
    await expect(page.getByRole('link', { name: /Analytics/ })).toBeVisible()
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

  test('navigates to Analytics page', async ({ page }) => {
    await page.getByRole('link', { name: /Analytics/ }).click()
    await expect(page).toHaveURL(/\/analytics/)
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
    await expect(page.getByRole('link', { name: /Analytics/ })).toBeVisible()
    await expect(page.getByRole('link', { name: /History/ })).toBeVisible()
  })
})
