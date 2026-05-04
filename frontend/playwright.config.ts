import { existsSync } from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

import { defineConfig, devices } from "@playwright/test"
import { config as loadDotenv } from "dotenv"

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// Align with backend + CI: repo-root env (docker compose uses these).
loadDotenv({ path: path.resolve(__dirname, "../.env") })
loadDotenv({ path: path.resolve(__dirname, "../.env.local"), override: true })
// Fill Playwright-only keys that often live under frontend/.env (e.g. MAILCATCHER_HOST).
loadDotenv({ path: path.resolve(__dirname, ".env"), override: false })

/** True when tests run inside `docker compose run playwright …`. */
const insideDockerRuntime = existsSync("/.dockerenv")

/**
 * URLs the browser navigates (service name resolves inside the Playwright container; host shell uses localhost).
 */
const browserBaseUrl =
  process.env.PLAYWRIGHT_BASE_URL?.trim() ??
  (insideDockerRuntime ? "http://frontend" : "http://127.0.0.1:5173")

/**
 * What this machine can curl for `webServer` readiness (Compose publishes nginx on host :5173).
 */
const webServerProbeOrigin =
  process.env.PLAYWRIGHT_PROBE_ORIGIN?.trim() ??
  (insideDockerRuntime
    ? new URL(browserBaseUrl).origin
    : "http://127.0.0.1:5173")

process.env.PLAYWRIGHT_MAIL_LINK_ORIGIN =
  process.env.PLAYWRIGHT_MAIL_LINK_ORIGIN?.trim() ??
  new URL(browserBaseUrl).origin

/**
 * Backend for Playwright helpers (`request`, private APIs). Preserve Compose `VITE_API_URL` in Docker.
 */
const playwrightApiBaseUrl =
  process.env.PLAYWRIGHT_VITE_API_URL?.trim() ||
  process.env.VITE_API_URL?.trim() ||
  (insideDockerRuntime ? "http://backend:8000" : "http://127.0.0.1:8000")
process.env.VITE_API_URL = playwrightApiBaseUrl

// In the Playwright container, nginx is already served by the `frontend` service — never spawn a second "server".
const reusePlaywrightWebServer = insideDockerRuntime
  ? true
  : process.env.PLAYWRIGHT_REUSE_SERVER === "1"
    ? true
    : process.env.PLAYWRIGHT_FORCE_NEW_WEB_SERVER === "1"
      ? false
      : !["true", "1"].includes(String(process.env.CI ?? "").toLowerCase())

/**
 * See https://playwright.dev/docs/test/configuration.
 */
export default defineConfig({
  globalSetup: "./playwright.global-setup.ts",
  testDir: "./tests",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? "blob" : "html",
  use: {
    baseURL: browserBaseUrl,
    trace: "on-first-retry",
  },

  projects: [
    { name: "setup", testMatch: /.*\.setup\.ts/ },

    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        storageState: "playwright/.auth/user.json",
      },
      dependencies: ["setup"],
    },
  ],

  // Wait for Compose `frontend` (nginx). Command must stay running — Playwright errors if it exits early.
  webServer: {
    command: `sh -c 'until curl -sf "${webServerProbeOrigin}/" >/dev/null 2>&1; do sleep 1; done; exec tail -f /dev/null'`,
    url: webServerProbeOrigin,
    reuseExistingServer: reusePlaywrightWebServer,
    timeout: 180_000,
  },
})
