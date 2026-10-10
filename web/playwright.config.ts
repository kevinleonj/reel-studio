import { defineConfig, devices } from "@playwright/test"

// Backend-free e2e suite (docs/UX.md §6): `astro preview` serves web/dist and every /api call is
// mocked with page.route in tests/e2e/support. Phone 390x844 and laptop 1280x800 (D17).
const PREVIEW_PORT = 4329
const BASE_URL = `http://localhost:${PREVIEW_PORT}` // hardcode-ok: the local preview server this config starts
const SERVER_START_MS = 60_000

export default defineConfig({
  testDir: "../tests/e2e",
  outputDir: "test-results",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: BASE_URL,
    screenshot: "only-on-failure",
    trace: "off",
  },
  projects: [
    {
      name: "phone",
      use: { ...devices["Desktop Chrome"], viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true },
    },
    {
      name: "laptop",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
    },
  ],
  webServer: {
    // --ignore-lock: Astro 7 refuses to start when its lock file names another preview server.
    command: `npm run preview -- --port ${PREVIEW_PORT} --ignore-lock`,
    url: BASE_URL,
    reuseExistingServer: false,
    timeout: SERVER_START_MS,
  },
})
