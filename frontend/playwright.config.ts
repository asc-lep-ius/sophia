import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  expect: {
    timeout: 5000,
  },
  fullyParallel: true,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "on-first-retry",
  },
  // The fixture API comes first so the preview server's own loads have
  // something to answer them. Both are torn down with the run.
  webServer: [
    {
      command: "node ./tests/e2e/fixture-api.mjs",
      reuseExistingServer: !process.env.CI,
      timeout: 30000,
      url: "http://127.0.0.1:8788/api/ready",
    },
    {
      command: "pnpm run build && pnpm run preview -- --host 127.0.0.1",
      env: {
        SOPHIA_E2E_AUTH: "1",
        SOPHIA_API_BASE_URL: "http://127.0.0.1:8788",
        SOPHIA_API_PROXY_TARGET: "http://127.0.0.1:8788",
      },
      reuseExistingServer: !process.env.CI,
      timeout: 120000,
      url: "http://127.0.0.1:4173/app",
    },
  ],
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
