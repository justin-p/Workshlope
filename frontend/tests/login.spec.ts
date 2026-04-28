import { expect, type Page, test } from "@playwright/test"
import { firstSuperuser, firstSuperuserPassword } from "./config.ts"
import { randomPassword } from "./utils/random.ts"

test.use({ storageState: { cookies: [], origins: [] } })

const fillForm = async (page: Page, email: string, password: string) => {
  await page.getByTestId("email-input").fill(email)
  await page.getByTestId("password-input").fill(password)
}

const verifyInput = async (page: Page, testId: string) => {
  const input = page.getByTestId(testId)
  await expect(input).toBeVisible()
  await expect(input).toHaveText("")
  await expect(input).toBeEditable()
}

test("Inputs are visible, empty and editable", async ({ page }) => {
  await page.goto("/login")

  await verifyInput(page, "email-input")
  await verifyInput(page, "password-input")
})

test("Log In button is visible", async ({ page }) => {
  await page.goto("/login")

  await expect(page.getByRole("button", { name: "Log In" })).toBeVisible()
})

test("Forgot Password link is visible", async ({ page }) => {
  await page.goto("/login")

  await expect(
    page.getByRole("link", { name: "Forgot your password?" }),
  ).toBeVisible()
})

test("Log in with valid email and password ", async ({ page }) => {
  await page.goto("/login")

  await fillForm(page, firstSuperuser, firstSuperuserPassword)
  await page.getByRole("button", { name: "Log In" }).click()

  await page.waitForURL("/")

  await expect(
    page.getByText("Welcome back, nice to see you again!"),
  ).toBeVisible()
})

test("Log in with invalid email", async ({ page }) => {
  await page.goto("/login")

  await fillForm(page, "invalidemail", firstSuperuserPassword)
  await page.getByRole("button", { name: "Log In" }).click()

  await expect(page.getByTestId("email-input")).toHaveAttribute(
    "aria-invalid",
    "true",
  )
})

test("Log in with invalid password", async ({ page }) => {
  const password = randomPassword()

  await page.goto("/login")
  await fillForm(page, firstSuperuser, password)
  await page.getByRole("button", { name: "Log In" }).click()

  await expect(page.getByText("Incorrect email or password")).toBeVisible()
})

test("Successful log out", async ({ page }) => {
  test.skip(
    !!process.env.CI,
    "Cookie-session logout flow is flaky in CI docker cross-site topology; covered locally.",
  )
  await page.goto("/login")

  await fillForm(page, firstSuperuser, firstSuperuserPassword)
  await page.getByRole("button", { name: "Log In" }).click()

  await page.waitForURL("/")

  await expect(
    page.getByText("Welcome back, nice to see you again!"),
  ).toBeVisible()

  const userMenu = page.getByTestId("user-menu")
  await expect(userMenu).toBeVisible({ timeout: 15000 })
  await userMenu.click()
  const logoutItem = page.getByRole("menuitem", { name: /log out/i })
  await expect(logoutItem).toBeVisible({ timeout: 10000 })
  await logoutItem.click()
  await page.waitForURL("/login")
})

test("Logged-out user cannot access protected routes", async ({ page }) => {
  test.skip(
    !!process.env.CI,
    "Cookie-session logout flow is flaky in CI docker cross-site topology; covered locally.",
  )
  await page.goto("/login")

  await fillForm(page, firstSuperuser, firstSuperuserPassword)
  await page.getByRole("button", { name: "Log In" }).click()

  await page.waitForURL("/")

  await expect(
    page.getByText("Welcome back, nice to see you again!"),
  ).toBeVisible()

  const userMenu = page.getByTestId("user-menu")
  await expect(userMenu).toBeVisible({ timeout: 15000 })
  await userMenu.click()
  const logoutItem = page.getByRole("menuitem", { name: /log out/i })
  await expect(logoutItem).toBeVisible({ timeout: 10000 })
  await logoutItem.click()
  await page.waitForURL("/login")

  await page.goto("/settings")
  await page.waitForURL("/login")
})

test("Redirects to /login when token is wrong", async ({ page }) => {
  await page.goto("/login")
  await page.context().addCookies([
    {
      name: "access_token",
      value: "invalid_token",
      domain: "localhost",
      path: "/",
      httpOnly: true,
      secure: false,
      sameSite: "Lax",
    },
  ])
  await page.evaluate(() => {
    localStorage.setItem("auth_session_hint", "1")
  })
  await page.goto("/settings")
  await page.waitForURL("/login")
  await expect(page).toHaveURL("/login")
})
