import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.PLAYWRIGHT_BASE_URL || "http://127.0.0.1:5173";
const browserExecutable = process.env.PLAYWRIGHT_BROWSER_EXECUTABLE;

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: true,
  use: {
    baseURL,
    trace: "on-first-retry",
    launchOptions: browserExecutable ? { executablePath: browserExecutable } : undefined,
  },
  webServer: process.env.PLAYWRIGHT_SKIP_WEBSERVER === "1" ? undefined : {
    command: "npm run dev",
    url: baseURL,
    reuseExistingServer: true,
    timeout: 30_000,
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
});
