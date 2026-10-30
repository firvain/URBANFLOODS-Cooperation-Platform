import { defineConfig, devices } from '@playwright/test'

/**
 * End-to-end tests against the running dev compose stack (frontend :5173, backend :8000,
 * Mailpit :8025). No `webServer`: start the stack with `docker compose up` first.
 * Override the targets with E2E_BASE_URL / E2E_MAILPIT_URL.
 */
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
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
