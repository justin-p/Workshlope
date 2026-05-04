import path from "node:path"
import { fileURLToPath } from "node:url"

import { defineConfig, devices } from "@playwright/test"
import { config as loadDotenv } from "dotenv"

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// Align with backend + CI: repo-root env (docker compose uses these).
loadDotenv({ path: path.resolve(__dirname, "../.env") })
loadDotenv({ path: path.resolve(__dirname, "../.env.local"), override: true })

/**
 * See https://playwright.dev/docs/test-configuration.
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
    baseURL: "http://localhost:5173",
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

  webServer: {
    command: "bun run dev",
    url: "http://localhost:5173",
    reuseExistingServer: !process.env.CI,
    env: {
      ...process.env,
      // /signup gating is build-time in Vite; keep enabled for the E2E dev server.
      VITE_USER_REGISTRATION_ENABLED: "true",
    },
  },
})
