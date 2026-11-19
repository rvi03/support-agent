import { defineConfig, devices } from "@playwright/test";

// S13 e2e (CP13.1-CP13.3): runs in the pinned Playwright image on the Colima host
// network (`make ui-e2e`), against the live platform from `make up`.
export default defineConfig({
  testDir: "e2e",
  timeout: 8 * 60_000,
  expect: { timeout: 10_000 },
  workers: 1,
  reporter: [["list"]],
  outputDir: "test-results",
  use: {
    baseURL: "http://localhost:5173",
    ...devices["Desktop Chrome"],
    viewport: { width: 1280, height: 800 },
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run dev",
    url: "http://localhost:5173",
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
