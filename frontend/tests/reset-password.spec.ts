import { expect, test } from "@playwright/test"
import { findLastEmail, mailFiltersToMailbox } from "./utils/mailcatcher"
import { randomEmail, randomPassword } from "./utils/random"
import {
  expectErrorToastDescription,
  expectSuccessToastDescription,
} from "./utils/sonnerToast.ts"
import { logInUser, signUpNewUser } from "./utils/user"

test.describe.configure({ mode: "serial", timeout: 120_000 })

test.use({ storageState: { cookies: [], origins: [] } })

/** Mail HTML uses backend FRONTEND_HOST; swap origin for the browser (e.g. http://frontend in Docker). */
function appUrlFromMailHref(href: string | null): string {
  expect(href, "reset link href missing in mail HTML").toBeTruthy()
  const appOrigin = (
    process.env.PLAYWRIGHT_MAIL_LINK_ORIGIN ?? "http://127.0.0.1:5173"
  ).replace(/\/+$/, "")
  const resolved = new URL(href!, appOrigin)
  return `${appOrigin}${resolved.pathname}${resolved.search}${resolved.hash}`
}

test("Password Recovery title is visible", async ({ page }) => {
  await page.goto("/recover-password")

  await expect(
    page.getByRole("heading", { name: "Password Recovery" }),
  ).toBeVisible()
})

test("Input is visible, empty and editable", async ({ page }) => {
  await page.goto("/recover-password")

  await expect(page.getByTestId("email-input")).toBeVisible()
  await expect(page.getByTestId("email-input")).toHaveText("")
  await expect(page.getByTestId("email-input")).toBeEditable()
})

test("Continue button is visible", async ({ page }) => {
  await page.goto("/recover-password")

  await expect(page.getByRole("button", { name: "Continue" })).toBeVisible()
})

test("User can reset password successfully using the link", async ({
  page,
  request,
}) => {
  const fullName = "Test User"
  const email = randomEmail()
  const password = randomPassword()
  const newPassword = randomPassword()

  // Sign up a new user
  await signUpNewUser(page, fullName, email, password)

  await page.goto("/recover-password")
  await page.getByTestId("email-input").fill(email)

  await page.getByRole("button", { name: "Continue" }).click()

  const emailData = await findLastEmail({
    request,
    filter: mailFiltersToMailbox(email),
    timeout: 30_000,
  })

  await page.goto(
    `${process.env.MAILCATCHER_HOST}/messages/${emailData.id}.html`,
  )

  const url = appUrlFromMailHref(
    await page
      .getByRole("link", { name: "Reset password" })
      .getAttribute("href"),
  )

  // Set the new password and confirm it
  await page.goto(url)

  await page.getByTestId("new-password-input").fill(newPassword)
  await page.getByTestId("confirm-password-input").fill(newPassword)
  await page.getByRole("button", { name: "Reset Password" }).click()
  await expectSuccessToastDescription(page, "Password updated successfully")

  // Check if the user is able to login with the new password
  await logInUser(page, email, newPassword)
})

test("Expired or invalid reset link", async ({ page }) => {
  const password = randomPassword()
  const invalidUrl = "/reset-password?token=invalidtoken"

  await page.goto(invalidUrl)

  await page.getByTestId("new-password-input").fill(password)
  await page.getByTestId("confirm-password-input").fill(password)
  await page.getByRole("button", { name: "Reset Password" }).click()

  await expectErrorToastDescription(page, "Invalid token")
})

test("Weak new password validation", async ({ page, request }) => {
  const fullName = "Test User"
  const email = randomEmail()
  const password = randomPassword()
  const weakPassword = "123"

  // Sign up a new user
  await signUpNewUser(page, fullName, email, password)

  await page.goto("/recover-password")
  await page.getByTestId("email-input").fill(email)
  await page.getByRole("button", { name: "Continue" }).click()

  const emailData = await findLastEmail({
    request,
    filter: mailFiltersToMailbox(email),
    timeout: 30_000,
  })

  await page.goto(
    `${process.env.MAILCATCHER_HOST}/messages/${emailData.id}.html`,
  )

  const url = appUrlFromMailHref(
    await page
      .getByRole("link", { name: "Reset password" })
      .getAttribute("href"),
  )

  // Set a weak new password
  await page.goto(url)
  await page.getByTestId("new-password-input").fill(weakPassword)
  await page.getByTestId("confirm-password-input").fill(weakPassword)
  await page.getByRole("button", { name: "Reset Password" }).click()

  await expect(
    page.getByText("Password must be at least 8 characters"),
  ).toBeVisible()
})
