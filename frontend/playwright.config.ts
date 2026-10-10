import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  // Specs beginning with `_` are MANUAL tools, not gate tests. `_screens.spec.ts`
  // captures the screenshots for review: it clicks through every screen at two
  // viewports, takes ~35 s, and flaked in the full suite on a slow first load.
  // A screenshot harness failing a push gate is noise with a real cost, so it is run
  // deliberately:  npx playwright test e2e/_screens.spec.ts
  // Excluded from the gate, but NOT unrunnable: naming the file explicitly is not enough
  // to beat testIgnore, so the capture harness needs a way back in. CAPTURE=1 provides it:
  //     CAPTURE=1 npx playwright test e2e/_screens.spec.ts
  testIgnore: process.env.CAPTURE ? [] : ['**/_*.spec.ts'],
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  // 45 s, not 15 s. `webServer` waits for Vite to LISTEN, but the dev server still
  // transforms modules on demand, so the FIRST page load of a run compiles the whole
  // app and can take tens of seconds on a machine that has just run 1000 backend
  // tests. TC-UIB-01 is usually that first test and timed out mid-assertion twice.
  //
  // A timeout exists to catch a hang, not to measure a dev-server cold start. The
  // individual `toBeVisible` expectations keep their own short waits, so a genuinely
  // broken page still fails fast — only the outer limit moved.
  timeout: 45_000,
  reporter: [
    ['list'],
    ['json', { outputFile: '../tests/logs/playwright_last.json' }],
  ],

  use: {
    baseURL: 'http://localhost:5173',
    headless: true,
    screenshot: 'only-on-failure',
    video: 'off',
    actionTimeout: 8_000,
  },

  // Auto-start Vite dev server before tests, shut down after
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: true,
    // 120 s, not 30 s. On the push gate Playwright runs immediately after the full
    // pytest suite, and Vite's cold start — dependency optimisation included — does not
    // finish in 30 s on a machine that has just been hammered. The result was
    // `TOTAL=0 PASSED=0 FAILED=0` and an aborted push: the stage correctly refused to
    // report success for having run nothing, but the cause was the timeout, not the code.
    timeout: 120_000,
  },

  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
})
