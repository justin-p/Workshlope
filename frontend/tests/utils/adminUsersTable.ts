import type { Page } from "@playwright/test"

/**
 * Admin users table uses client-side pagination; raise the page size when the
 * controls are visible so row locators still match under parallel Playwright workers.
 */
export async function maximizeAdminUsersTablePageSize(page: Page) {
  const rowsCombo = page.getByRole("combobox", { name: "Rows per page" })
  if ((await rowsCombo.count()) === 0) return
  await rowsCombo.waitFor({ state: "visible" })
  await rowsCombo.click()
  await page.getByRole("option", { name: "100" }).click()
}
