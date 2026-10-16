import { test, expect } from '@playwright/test'
import { loginAs, mockApi } from './helpers'

/**
 * Phase 1: no image or video to the ERP, enforced by the code (spec §16.3, owner 2026-10-16).
 *
 *   TC-UIG-01  a refused endpoint shows its sentence and NO tickbox (absent, not disabled);
 *              an ordinary endpoint keeps its tickbox (control)
 *   TC-UIG-02  a stored list that still holds a camera endpoint (cabinet 1 had all four) is
 *              offered for saving, and the saved list no longer holds it
 */
const SENTENCE = "Camera endpoints are not allowed to the ERP in Phase 1 — owner's decision, GDPR"

async function mockGateway(page: import('@playwright/test').Page, stored: string[], puts: unknown[]) {
  await page.route('**/api/admin/ext-api/catalog', (r) => r.fulfill({ json: {
    endpoints: [
      { id: 'pedestals.health', path: '/api/pedestals/health', method: 'GET', category: 'Health',
        allow_bidirectional: false, refused_reason: null },
      { id: 'camera.frame_ext', path: '/api/ext/pedestals/{id}/camera/frame', method: 'GET',
        category: 'Camera', allow_bidirectional: false, image: true, refused_reason: SENTENCE },
    ],
    events: [],
  } }))
  await page.route('**/api/admin/ext-api/config', async (r) => {
    if (r.request().method() === 'PUT') {
      const body = r.request().postDataJSON()
      puts.push(body)
      return r.fulfill({ json: { ...body, active: false, verified: false, api_key: null,
        verification_results: null } })
    }
    return r.fulfill({ json: {
      allowed_endpoints: stored.map((id) => ({ id, mode: 'monitor' })), webhook_url: null,
      allowed_events: [], active: true, verified: false, api_key: null, verification_results: null,
    } })
  })
}

test('TC-UIG-01 a refused endpoint has its sentence and no tickbox', async ({ page }) => {
  await loginAs(page, 'admin')
  await mockApi(page)
  await mockGateway(page, ['pedestals.health'], [])
  await page.goto('/api-gateway')
  const refused = page.getByTestId('refused-camera.frame_ext')
  await expect(refused).toHaveText(SENTENCE)
  const camRow = refused.locator('xpath=ancestor::div[contains(@class,"border-b")][1]')
  await expect(camRow.locator('input[type="checkbox"]')).toHaveCount(0)
  const healthRow = page.getByText('pedestals.health', { exact: true })
    .locator('xpath=ancestor::div[contains(@class,"border-b")][1]')
  await expect(healthRow.locator('input[type="checkbox"]')).toHaveCount(1)
})

test('TC-UIG-02 an older stored camera entry is dropped when the list is saved', async ({ page }) => {
  const puts: unknown[] = []
  await loginAs(page, 'admin')
  await mockApi(page)
  await mockGateway(page, ['pedestals.health', 'camera.frame_ext'], puts)
  await page.goto('/api-gateway')
  const save = page.getByRole('button', { name: 'Save Endpoints' })
  await expect(save).toBeEnabled()
  await save.click()
  await expect.poll(() => puts.length).toBe(1)
  const ids = (puts[0] as { allowed_endpoints: { id: string }[] }).allowed_endpoints.map((e) => e.id)
  expect(ids).toEqual(['pedestals.health'])
})
