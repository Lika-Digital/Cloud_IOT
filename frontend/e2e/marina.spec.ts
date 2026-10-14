import { test, expect, type Page } from '@playwright/test'
import { loginAs, mockApi } from './helpers'

/**
 * Marina dashboard — boot, and the three behaviours a JSON response cannot show.
 *
 * These are fully mocked with `page.route`, so they need no backend. That matters: the e2e
 * runner used to exit 0 when nothing answered on :8000, which skipped these specs even
 * though they never required it.
 *
 *   TC-UIB-01  the app BOOTS — real bundle, real router, no error boundary
 *   TC-UIE-01  a null-and-unknown-heavy payload renders without breaking
 *   TC-UIE-02  a 500 does not blank the dashboard
 *   TC-UIE-03  a timeout does not blank the dashboard
 *   TC-UIE-04  stale data is kept and LABELLED when a refresh fails
 *   TC-UIR-03  an unavailable control is ABSENT from the DOM, not disabled
 *   TC-UIS-02  a stale valve reads differently from an idle one
 *   TC-UIR-08  no page-level horizontal scroll at 360 px
 */

/** A healthy pedestal: 4 berths on 4 sockets, 2 shared valves. The Krk layout. */
function healthyCore() {
  return {
    pedestals: [{
      pedestal_id: 1,
      cabinet_id: 'MAR_KRK_ORM_01',
      dock: 'A',
      reachable: true,
      smart_mode: true,
      berths: [1, 2, 3, 4].map((n) => ({
        berth_id: 100 + n,
        berth_number: n,
        status: n === 3 ? 'attention' : 'ok',
        status_code: n === 3 ? 'water_leak' : 'ok',
        status_sentence: n === 3 ? 'Water leak detected' : null,
        status_rank: n === 3 ? 3 : 9,
        power: {
          outlet: `Q${n}`,
          on: n === 1,
          state: n === 1 ? 'active' : 'idle',
          amps: n === 1 ? 9.5 : null,
          unit: 'A',
          available: true,
          unavailable_reason: null,
        },
        occupied: n !== 2,
        occupied_known: true,
        vessel_matches: n === 1 ? true : null,
        vessel_match_configured: n === 1,
        alarm_count: n === 3 ? 2 : 0,
      })),
      water_outlets: [
        {
          outlet: 'V1', on: true, state: 'active', litres_per_min: 12.4, unit: 'L/min',
          rated_liters_per_min: 20, in_use: true, available: true, unavailable_reason: null,
        },
        {
          outlet: 'V2', on: false, state: 'idle', litres_per_min: 0, unit: 'L/min',
          rated_liters_per_min: 20, in_use: false, available: true, unavailable_reason: null,
        },
      ],
      light: { on: true, scope: 'pedestal', available: true, unavailable_reason: null },
      guard: { state: 'on', sentence: 'Guard on', scope: 'pedestal' },
      alarm_count: 2,
    }],
  }
}

/**
 * Everything that can legitimately be null or unknown, all at once.
 *
 * `unknown` is a real state in eleven of our status sentences, so it is not an edge case —
 * it is the state a silent cabinet produces, and a silent cabinet is the common failure.
 */
function nullHeavyCore() {
  return {
    pedestals: [{
      pedestal_id: 1,
      cabinet_id: null,
      dock: null,
      reachable: false,
      smart_mode: true,
      berths: [
        {
          berth_id: 201, berth_number: null,
          status: 'unknown', status_code: 'no_contact',
          status_sentence: 'No contact with this pedestal', status_rank: 1,
          power: {
            outlet: null, on: false, state: 'unknown', amps: null, unit: 'A',
            available: false, unavailable_reason: 'no_socket',
          },
          occupied: false, occupied_known: false,
          vessel_matches: null, vessel_match_configured: false,
          alarm_count: 0,
        },
      ],
      water_outlets: [{
        outlet: 'V1', on: false, state: 'unknown', litres_per_min: null, unit: 'L/min',
        rated_liters_per_min: null, in_use: false,
        available: false, unavailable_reason: 'standalone',
      }],
      light: { on: false, scope: 'pedestal', available: false, unavailable_reason: 'standalone' },
      guard: { state: 'unavailable', sentence: 'Guard unavailable', scope: 'pedestal' },
      alarm_count: 0,
    }],
  }
}

async function mockCore(page: Page, body: unknown) {
  await page.route('**/api/marina/berths', (route) => route.fulfill({ json: body }))
}

/*
 * THERE IS DELIBERATELY NO CATCH-ALL MOCK HERE.
 *
 * The first attempt added one — `page.route('**\/api/**')` answering `{}` — to silence the
 * app shell's own polling (unread chat, hardware alarms, error counts) so the console would
 * be clean. It took the whole page down: the shell's widgets do not tolerate `{}` where they
 * expect an array, the ErrorBoundary swallowed the tree, and all eight specs failed with
 * `marina-dashboard` not found. Two of them had been passing before.
 *
 * The shell's unmocked calls are left to fail, because that is not what these specs are
 * about, and the assertion is scoped instead: `pageerror` means the app THREW, which is
 * always a defect; a console error from a failed fetch is a different claim, and TC-UIE-02
 * and TC-UIE-03 deliberately cause one.
 */

/**
 * Navigate, and collect the two kinds of failure SEPARATELY.
 *
 * `pageerror` is an uncaught exception — the app threw, and that is always a defect.
 * A console error is usually a failed network call, which is a different claim entirely:
 * TC-UIE-02 and TC-UIE-03 deliberately CAUSE one and assert the UI copes. Collapsing the two
 * made a test of error-handling fail for having handled an error.
 */
async function gotoMarina(page: Page) {
  const thrown: string[] = []
  const logged: string[] = []
  page.on('pageerror', (e) => thrown.push(String(e)))
  page.on('console', (m) => {
    if (m.type() === 'error') logged.push(m.text())
  })
  await page.goto('/marina')
  return { thrown, logged }
}

test.beforeEach(async ({ page }) => {
  await loginAs(page, 'monitor')
})

// ═══ TC-UIB-01 ══════════════════════════════════════════════════════════════

test('TC-UIB-01 the marina dashboard boots and renders berth rows', async ({ page }) => {
  // The gate that matters most. A component suite passing while the app cannot start is the
  // same failure in a different place — 803 tests once passed while the guard worker had no
  // entrypoint at all. This fails if the bundle does not build, the route is wrong, or CORE's
  // shape changed under the renderer.
  await mockCore(page, healthyCore())
  const { thrown } = await gotoMarina(page)

  await expect(page.getByTestId('marina-dashboard')).toBeVisible()
  await expect(page.getByRole('link', { name: /Berth 3/ })).toBeVisible()
  await expect(page.getByText('Water leak detected')).toBeVisible()
  // Status is colour + icon + WORD. The word is what this asserts, because it is the part a
  // colour-blind user and a screen reader both depend on.
  //
  // `exact: true` matters: the filter button reads 'Needs attention (2)', so a substring
  // match finds the button as well as the badge and the assertion becomes ambiguous —
  // which is how it passed alone and failed in the full suite. The badge is the one that
  // carries the rule.
  await expect(page.getByText('Needs attention', { exact: true }).first()).toBeVisible()

  await expect(page.getByTestId('marina-error')).toHaveCount(0)
  expect(thrown, `the app threw on boot:\n${thrown.join('\n')}`).toEqual([])
})

// ═══ TC-UIE-01 ══════════════════════════════════════════════════════════════

test('TC-UIE-01 a null-and-unknown-heavy payload renders without breaking', async ({ page }) => {
  // Every nullable field null at once. The failure this prevents is a `.toFixed()` on null,
  // which blanks the whole route behind an error boundary — so one silent cabinet takes out
  // the dashboard for every other berth too.
  await mockCore(page, nullHeavyCore())
  const { thrown } = await gotoMarina(page)

  await expect(page.getByTestId('marina-dashboard')).toBeVisible()
  await expect(page.getByText('No contact with this pedestal')).toBeVisible()
  await expect(page.getByText('Not known').first()).toBeVisible()
  // A missing berth number renders as a dash, not as "Berth null" or "Berth undefined".
  await expect(page.getByRole('link', { name: /Berth —/ })).toBeVisible()
  // An unknown figure is an em dash, never 0 — "we did not measure" is not "measured nothing".
  await expect(page.getByTitle('Not measured').first()).toBeVisible()

  expect(thrown, `rendering nulls threw:\n${thrown.join('\n')}`).toEqual([])
})

// ═══ TC-UIR-03 ══════════════════════════════════════════════════════════════

test('TC-UIR-03 an unavailable control is absent from the DOM, not disabled', async ({ page }) => {
  // Asserted by querying for the button and expecting NOTHING. A `disabled` attribute would
  // satisfy "cannot be clicked" while still showing marina staff a control that looks like
  // it should work — which is the rule's whole point.
  await mockCore(page, nullHeavyCore())
  await gotoMarina(page)

  await expect(page.getByTestId('marina-dashboard')).toBeVisible()
  await expect(page.getByRole('button', { name: /Turn (on|off)/ })).toHaveCount(0)
  // And the sentence is there in its place.
  await expect(page.getByText('No electricity socket at this berth')).toBeVisible()
})

// ═══ TC-UIS-02 ══════════════════════════════════════════════════════════════

test('TC-UIS-02 a stale valve reads differently from an idle one', async ({ page }) => {
  // `unknown` and `idle` must not collapse. "The cabinet has not told us" and "the outlet is
  // free" lead to different actions, and a customer sent to an outlet we know nothing about
  // walks to the far end of the pontoon to find out.
  await mockCore(page, nullHeavyCore())
  await gotoMarina(page)

  await expect(
    page.getByText('The pedestal has not reported this outlet recently.'),
  ).toBeVisible()
  await expect(page.getByText('FREE')).toHaveCount(0)
})

// ═══ TC-UIE-02 / TC-UIE-03 ══════════════════════════════════════════════════

test('TC-UIE-02 a 500 does not blank the dashboard', async ({ page }) => {
  // A dashboard that goes blank because one call failed is worse than one that says what
  // happened: the operator cannot tell a broken server from an empty marina.
  await page.route('**/api/marina/berths', (route) =>
    route.fulfill({ status: 500, json: { detail: 'boom' } }))
  const { thrown } = await gotoMarina(page)

  await expect(page.getByTestId('marina-error')).toBeVisible()
  await expect(page.getByText(/could not answer/i)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible()
  // A logged 500 is EXPECTED here — the test caused it. What must not happen is an
  // uncaught exception, which would take the route down behind an error boundary.
  expect(thrown, `handling a 500 threw:\n${thrown.join('\n')}`).toEqual([])
})

test('TC-UIE-03 a timeout does not blank the dashboard', async ({ page }) => {
  // An aborted request, which is what a dead NUC on the far end of a marina wifi link looks
  // like from the browser. Distinct from a 500: nothing answers at all.
  await page.route('**/api/marina/berths', (route) => route.abort('timedout'))
  await gotoMarina(page)

  await expect(page.getByTestId('marina-error')).toBeVisible()
  // An aborted request surfaces as a TIMEOUT in axios, not as a bare network error, so
  // the message is 'took too long' rather than 'cannot reach'. Both are in the error
  // vocabulary and both are correct for their cause; the first version of this assertion
  // simply named the wrong one. Accepting either would have made the test indifferent to
  // which cause produced it, so it asserts the specific right message.
  await expect(page.getByText(/took too long/i)).toBeVisible()
})

// ═══ TC-UIE-04 ══════════════════════════════════════════════════════════════

test('TC-UIE-04 a failed refresh keeps the rows and labels them stale', async ({ page }) => {
  // The first load succeeds, the refresh fails. Blanking the screen would lose the
  // operator's place and tell them nothing; showing stale readings without saying so would
  // be worse. So: keep them, and label them.
  let calls = 0
  await page.route('**/api/marina/berths', (route) => {
    calls += 1
    if (calls === 1) return route.fulfill({ json: healthyCore() })
    return route.fulfill({ status: 503, json: { detail: 'restarting' } })
  })

  await gotoMarina(page)
  await expect(page.getByRole('link', { name: /Berth 3/ })).toBeVisible()

  // The page refreshes on a 15 s interval and listens for nothing else, so the wait
  // is the mechanism. A dispatched 'focus' event did nothing — asserting against a
  // trigger the component does not have would have made this test pass for the wrong
  // reason once the banner appeared for any other cause.
  await expect(page.getByTestId('marina-stale-banner')).toBeVisible({ timeout: 25_000 })
  await expect(page.getByText(/may be out of date/i)).toBeVisible()
  // The rows are STILL THERE.
  await expect(page.getByRole('link', { name: /Berth 3/ })).toBeVisible()
})

// ═══ TC-UIR-08 ══════════════════════════════════════════════════════════════

test('TC-UIR-08 no page-level horizontal scroll at 360 px', async ({ page }) => {
  // Phone-first is not a preference: this is read standing on a pontoon. A page that scrolls
  // sideways hides the status word, which is the one thing the row exists to show.
  await page.setViewportSize({ width: 360, height: 740 })
  await mockCore(page, healthyCore())
  await gotoMarina(page)

  await expect(page.getByTestId('marina-dashboard')).toBeVisible()
  const overflow = await page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow, `page scrolls ${overflow}px sideways at 360px wide`).toBeLessThanOrEqual(1)
})

// ═══ TC-UIN-01 — block 4, nav: Analytics is L3 ═══════════════════════════════

test('TC-UIN-01 Analytics is not in the nav; berth detail opens it for its pedestal', async ({ page }) => {
  // Block 4, nav (ui_v2_audit §7 #9 — NOT the owner's finding 9, which is retention_service).
  // Analytics was top-level. It is reached from a berth now, with that berth's
  // pedestal preselected — a nav item nobody needs on the pier is one more thing to read past.
  await mockCore(page, healthyCore())
  const berth = healthyCore().pedestals[0].berths[0]
  await page.route('**/api/marina/berths/101', (route) => route.fulfill({
    json: {
      ...berth,
      pedestal_id: 7,
      cabinet_id: 'MAR_KRK_ORM_01',
      outlet_spec: { outlet: 'Q1', rated_amps: 32, phases: 3, meter_type: null },
      consumption: { kwh: 12.5, source: 'register', note: '' },
      reference_image: null,
      guard: { state: 'on', sentence: 'Guard on', scope: 'pedestal' },
      guard_scope_note: 'One camera per pedestal.',
    },
  }))
  await gotoMarina(page)
  await expect(page.getByTestId('marina-dashboard')).toBeVisible()
  // The accessible name is "📊 Analytics" — an anchored /^Analytics/ never matched and passed
  // on the old code; so first prove the nav is there at all.
  await expect(page.getByRole('link', { name: /History/ }).first()).toBeVisible()
  await expect(page.getByRole('link', { name: /Analytics/ })).toHaveCount(0)

  await page.goto('/marina/berth/101')
  await expect(page.getByTestId('berth-detail')).toBeVisible()
  const link = page.getByRole('link', { name: /Pedestal consumption history/ })
  await expect(link).toHaveAttribute('href', '/analytics?pedestal=7')
})

// ═══ TC-UIN-02 — the setup wizard is admin only, in the ROUTE, not just the menu ══════

test('TC-UIN-02 staff typing the wizard address do not get the wizard; admin does', async ({ page }) => {
  // Saving the wizard is require_admin. A page staff can open but never save is a false offer;
  // hiding it from the menu alone would leave it one typed address away (§0.2, 2026-10-15).
  await mockCore(page, healthyCore())
  await page.goto('/marina/setup/1')
  await expect(page).toHaveURL(/\/dashboard$/)
  await expect(page.getByTestId('marina-setup')).toHaveCount(0)

  // Positive control: the same address, as admin, renders the wizard — so the redirect above
  // is the role, not a broken route. (A later init script overrides the monitor login.)
  // The admin shell polls more endpoints than the monitor's, and crashes on unmocked ones —
  // so it gets the shared mocks, and the marina mock again on top (last route wins).
  await loginAs(page, 'admin')
  await mockApi(page)
  await mockCore(page, healthyCore())
  await page.goto('/marina/setup/1')
  await expect(page.getByTestId('marina-setup')).toBeVisible()
})

// ═══ TC-UIP-01 — <PhaseBlock>: per phase, in words, absent when there is nothing per phase ══

test('TC-UIP-01 a three-phase socket shows Phase 1/2/3 in berth detail; single-phase shows none', async ({ page }) => {
  await mockCore(page, healthyCore())
  const berth = healthyCore().pedestals[0].berths[0]
  const detail = (phase_amps: unknown) => ({
    ...berth,
    power: { ...berth.power, phase_amps },
    pedestal_id: 1,
    cabinet_id: 'MAR_KRK_ORM_01',
    outlet_spec: { outlet: 'Q1', rated_amps: 32, phases: 3, meter_type: null },
    consumption: { kwh: 12.5, source: 'register', note: '' },
    reference_image: null,
    guard: { state: 'on', sentence: 'Guard on', scope: 'pedestal' },
    guard_scope_note: 'One camera per pedestal.',
  })
  let body = detail([10.04, null, 11])
  await page.route('**/api/marina/berths/101', (route) => route.fulfill({ json: body }))

  await page.goto('/marina/berth/101')
  const block = page.getByTestId('phase-block')
  await expect(block).toBeVisible()
  await expect(block).toContainText('Phase 1')
  await expect(block).toContainText('10.04 A')
  await expect(block).toContainText('Phase 3')
  await expect(block).toContainText('11 A')
  // The phase the cabinet did not send is a dash, never "0 A"; and never the word "L1".
  await expect(block.locator('dd').nth(1)).toHaveText('—')
  await expect(page.getByTestId('berth-detail')).not.toContainText(/\bL[123]\b/)

  // Single-phase / nothing running / stale: null — the block is ABSENT from the DOM.
  body = detail(null)
  await page.reload()
  await expect(page.getByTestId('berth-detail')).toBeVisible()
  await expect(page.getByTestId('phase-block')).toHaveCount(0)
})

// ═══ TC-UIRC-01..04 — row controls (block 4) ══════════════════════════════════════════

/** The healthy pedestal, with the actions the server would offer a control account. */
function controllableCore() {
  const core = healthyCore()
  const p = core.pedestals[0]
  p.berths.forEach((b) => {
    Object.assign(b.power, b.power.on
      ? { action: 'off', available: true, unavailable_reason: null }
      : { action: null, available: false, unavailable_reason: 'nothing_plugged' })
  })
  Object.assign(p.water_outlets[0], { action: 'off', available: true, unavailable_reason: null })
  Object.assign(p.water_outlets[1], { action: null, available: false, unavailable_reason: 'needs_scan' })
  Object.assign(p.light, { action: 'off', available: true, unavailable_reason: null })
  return core
}

test('TC-UIRC-01 an offered action is a button that sends exactly that command', async ({ page }) => {
  await mockCore(page, controllableCore())
  const sent: { url: string; body: unknown }[] = []
  await page.route('**/api/controls/**', async (route) => {
    sent.push({ url: route.request().url(), body: route.request().postDataJSON() })
    await route.fulfill({ json: { status: 'sent' } })
  })
  await gotoMarina(page)
  await page.getByRole('button', { name: 'All (4)' }).click()

  // Power on berth 1 is running: "Turn off", confirmed first — it ends someone's session.
  const power = page.getByTestId('power-101')
  await power.getByRole('button', { name: 'Turn off' }).click()
  await expect(power).toContainText('Turn off power at berth 1? The session there ends.')
  expect(sent).toHaveLength(0)
  await power.getByRole('button', { name: 'Yes, turn off' }).click()
  await expect(power.getByRole('status')).toHaveText('Sent. The line changes when the pedestal reports back.')
  expect(sent).toEqual([{ url: expect.stringMatching(/\/api\/controls\/pedestal\/1\/socket\/Q1\/cmd$/),
                          body: { action: 'stop' } }])

  // The light names every berth it covers before it acts.
  const light = page.getByTestId('light')
  await light.getByRole('button', { name: 'Turn off' }).click()
  await expect(light).toContainText('This light covers berths 1, 2, 3 and 4. Turn it off for all of them?')
  await light.getByRole('button', { name: 'Yes, turn off' }).click()
  await expect.poll(() => sent.length).toBe(2)
  expect(sent[1].url).toMatch(/\/api\/controls\/pedestal\/1\/led$/)
  expect(sent[1].body).toEqual({ color: 'green', state: 'off' })
})

test('TC-UIRC-02 water without a scan: no button, and the sentence says why (§15)', async ({ page }) => {
  await mockCore(page, controllableCore())
  await gotoMarina(page)
  const v2 = page.getByTestId('water-V2')
  await expect(v2).toContainText('Water opens after the customer scans their card at the valve')
  await expect(v2.getByRole('button')).toHaveCount(0)
  // Nothing plugged in: likewise a sentence, not a "Turn on" the endpoint would refuse.
  await page.getByRole('button', { name: 'All (4)' }).click()
  const p2 = page.getByTestId('power-102')
  await expect(p2).toContainText('Nothing is plugged in')
  await expect(p2.getByRole('button')).toHaveCount(0)
})

test('TC-UIRC-03 a refusal shows the server\'s sentence; no answer says it is not known', async ({ page }) => {
  const core = controllableCore()
  Object.assign(core.pedestals[0].water_outlets[1], { action: 'on', available: true, unavailable_reason: null })
  await mockCore(page, core)
  let calls = 0
  await page.route('**/api/controls/**', (route) => {
    calls += 1
    return calls === 1
      ? route.fulfill({ status: 409, json: { detail: 'No valid NFC reservation for V2: water opens only after a card is scanned at this valve.' } })
      : route.abort('timedout')
  })
  await gotoMarina(page)
  const v2 = page.getByTestId('water-V2')
  await v2.getByRole('button', { name: 'Turn on' }).click()
  await expect(v2.getByRole('alert')).toHaveText(
    'Not switched: No valid NFC reservation for V2: water opens only after a card is scanned at this valve.')
  // A request that never answered is NOT "not switched" — the command may have gone out.
  await v2.getByRole('button', { name: 'Turn on' }).click()
  await expect(v2.getByRole('alert')).toContainText('Whether it switched is not known')
  await expect(v2.getByRole('alert')).not.toContainText('Not switched')
})

test('TC-UIRC-04 every reason has its own sentence; out of contact is not "switching itself"', async ({ page }) => {
  const core = controllableCore()
  const p = core.pedestals[0]
  p.reachable = false
  for (const f of [...p.berths.map((b) => b.power), ...p.water_outlets, p.light]) {
    Object.assign(f, { action: null, available: false, unavailable_reason: 'no_contact' })
  }
  await mockCore(page, core)
  await gotoMarina(page)
  await page.getByRole('button', { name: 'All (4)' }).click()
  await expect(page.getByRole('button', { name: /Turn (on|off)/ })).toHaveCount(0)
  await expect(page.getByText('No contact with the pedestal, so it cannot be switched from here').first()).toBeVisible()
  await expect(page.getByText('The pedestal is switching this itself')).toHaveCount(0)
})
