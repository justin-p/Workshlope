import type { Page } from "@playwright/test"
import { expect } from "@playwright/test"

/** Any role dashboard path after login (matches full Playwright navigation URL string). */
export const LOGGED_IN_DASHBOARD_URL_RE =
  /\/dashboard\/(?:trainee|instructor|admin)(?:\/|$|\?)/

export async function expectLandingAfterLogin(page: Page) {
  await page.waitForURL(LOGGED_IN_DASHBOARD_URL_RE)
  await expect(page.getByTestId("dashboard-home-root")).toBeVisible()
}
