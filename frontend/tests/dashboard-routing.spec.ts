import { expect, test } from "@playwright/test"
import { firstSuperuser, firstSuperuserPassword } from "./config.ts"

test.use({ storageState: { cookies: [], origins: [] } })

test("superuser without instructor flag lands on admin home after login", async ({
  page,
}) => {
  await page.goto("/login")
  await page.getByTestId("email-input").fill(firstSuperuser)
  await page.getByTestId("password-input").fill(firstSuperuserPassword)
  await page.getByRole("button", { name: "Log In" }).click()
  await page.waitForURL("/dashboard/admin")
  await expect(
    page.getByRole("heading", { level: 1, name: "Admin Home" }),
  ).toBeVisible()
  await expect(page.getByTestId("dashboard-stub-rail-admin")).toBeVisible()
  await expect(page.getByTestId("dashboard-workshop-sessions")).toBeVisible()
})

test("root path redirects superuser to role dashboard", async ({ page }) => {
  await page.goto("/login")
  await page.getByTestId("email-input").fill(firstSuperuser)
  await page.getByTestId("password-input").fill(firstSuperuserPassword)
  await page.getByRole("button", { name: "Log In" }).click()
  await page.waitForURL("/dashboard/admin")
  await page.goto("/")
  await page.waitForURL("/dashboard/admin")
})

test("instructor dashboard redirects non-instructor superuser to their home", async ({
  page,
}) => {
  await page.goto("/login")
  await page.getByTestId("email-input").fill(firstSuperuser)
  await page.getByTestId("password-input").fill(firstSuperuserPassword)
  await page.getByRole("button", { name: "Log In" }).click()
  await page.waitForURL("/dashboard/admin")
  await page.goto("/dashboard/instructor")
  await page.waitForURL("/dashboard/admin")
})
