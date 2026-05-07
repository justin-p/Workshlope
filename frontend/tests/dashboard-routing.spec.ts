import { expect, test } from "@playwright/test"
import { firstSuperuser, firstSuperuserPassword } from "./config.ts"
import { createUser } from "./utils/privateApi"
import { randomEmail } from "./utils/random"

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

test("login tolerates stale access token without redirect loop", async ({
  page,
}) => {
  await page.addInitScript(() => {
    localStorage.setItem("access_token", "stale-token")
  })

  await page.goto("/login")
  await page.waitForURL("/login")
  await expect(
    page.getByRole("heading", { name: "Login to your account" }),
  ).toBeVisible()
  await expect
    .poll(async () =>
      page.evaluate(() => window.localStorage.getItem("access_token")),
    )
    .toBeNull()
})

test("trainee dashboard shows settings rail shortcut", async ({ browser }) => {
  const email = randomEmail()
  const password = "changethis123"
  await createUser({ email, password })

  const context = await browser.newContext({
    storageState: { cookies: [], origins: [] },
  })
  const page = await context.newPage()
  await page.goto("/login")
  await page.getByTestId("email-input").fill(email)
  await page.getByTestId("password-input").fill(password)
  await page.getByRole("button", { name: "Log In" }).click()
  await page.waitForURL("/dashboard/trainee")

  await expect(page.getByTestId("dashboard-stub-rail-trainee")).toBeVisible()
  await page.getByRole("link", { name: "Open settings" }).click()
  await page.waitForURL("/settings")
  await context.close()
})

test("admin dashboard shows admin rail shortcut", async ({ page }) => {
  await page.goto("/login")
  await page.getByTestId("email-input").fill(firstSuperuser)
  await page.getByTestId("password-input").fill(firstSuperuserPassword)
  await page.getByRole("button", { name: "Log In" }).click()
  await page.waitForURL("/dashboard/admin")

  await expect(page.getByTestId("dashboard-stub-rail-admin")).toBeVisible()
  await page.getByRole("link", { name: "Open admin" }).click()
  await page.waitForURL("/admin")
})

test("admin can access workshops hub route", async ({ page }) => {
  await page.goto("/login")
  await page.getByTestId("email-input").fill(firstSuperuser)
  await page.getByTestId("password-input").fill(firstSuperuserPassword)
  await page.getByRole("button", { name: "Log In" }).click()
  await page.waitForURL("/dashboard/admin")

  await page.goto("/workshops")
  await page.waitForURL("/workshops")
  await expect(
    page.getByRole("heading", { level: 1, name: "Workshops hub" }),
  ).toBeVisible()
})

test("trainee dashboard shows expected stub rail cards", async ({
  browser,
}) => {
  const email = randomEmail()
  const password = "changethis123"
  await createUser({ email, password })

  const context = await browser.newContext({
    storageState: { cookies: [], origins: [] },
  })
  const page = await context.newPage()
  await page.goto("/login")
  await page.getByTestId("email-input").fill(email)
  await page.getByTestId("password-input").fill(password)
  await page.getByRole("button", { name: "Log In" }).click()
  await page.waitForURL("/dashboard/trainee")

  const rail = page.getByTestId("dashboard-stub-rail-trainee")
  await expect(rail).toContainText("Continue learning")
  await expect(rail).toContainText("Badges & progress")
  await expect(rail).toContainText("Account")
  await context.close()
})

test("instructor can access workshops sync card", async ({ browser }) => {
  const email = randomEmail()
  const password = "changethis123"
  await createUser({ email, password, is_instructor: true })

  const context = await browser.newContext({
    storageState: { cookies: [], origins: [] },
  })
  const page = await context.newPage()
  await page.goto("/login")
  await page.getByTestId("email-input").fill(email)
  await page.getByTestId("password-input").fill(password)
  await page.getByRole("button", { name: "Log In" }).click()
  await page.waitForURL("/dashboard/instructor")

  await page.goto("/workshops")
  await page.waitForURL("/workshops")
  await expect(page.getByTestId("workshop-lesson-repo-sync-card")).toBeVisible()
  await context.close()
})
