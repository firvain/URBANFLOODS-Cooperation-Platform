import { defineConfig, devices } from '@playwright/test'

/**
 * Two suites, never mixed:
 *
 * - `npm run e2e`: end-to-end tests against the running dev compose stack (frontend :5173,
 *   backend :8000, Mailpit :8025). No `webServer`: start the stack with `docker compose up` first.
 *   Override the targets with E2E_BASE_URL / E2E_MAILPIT_URL. Skips `e2e/smoke/`.
 * - `npm run e2e:smoke` (E2E_SMOKE=1): the production-mode smoke suite in `e2e/smoke/`, against
 *   the production stack started by `scripts/smoke.sh` (nginx on :3002, Mailpit API on :8026).
 *   Runs only `*.smoke.spec.ts`.
 */
const SMOKE = !!process.env.E2E_SMOKE

if (SMOKE) {
  // Defaults for the smoke stack (docker-compose.smoke.yml); the helpers read these too. The
  // config is evaluated in every worker, so the workers see them as well.
  process.env.E2E_BASE_URL ??= 'http://localhost:3002'
  process.env.E2E_MAILPIT_URL ??= 'http://localhost:8026'
}

export default defineConfig({
  testDir: 'e2e',
  // One shared backend and mailbox: run files one after another.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:5173',
    // The UI language follows navigator.languages; pin English so the en.json strings match.
    locale: 'en-GB',
    timezoneId: 'Europe/Athens',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: SMOKE
    ? [
        {
          name: 'smoke',
          testDir: 'e2e/smoke',
          testMatch: '**/*.smoke.spec.ts',
          // No retries: the auth limits (5 registrations, 3 resends per hour and IP) are real
          // here, and a retried serial group would register its accounts again.
          retries: 0,
          use: { ...devices['Desktop Chrome'] },
        },
      ]
    : [
        {
          name: 'chromium',
          testIgnore: '**/smoke/**',
          use: { ...devices['Desktop Chrome'] },
        },
      ],
})
