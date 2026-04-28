import { expect, type Page, test } from "@playwright/test"

import { createPendingViaBridge, deleteAllPending } from "./utils/bridgeToken"
import { randomEmail, randomPassword } from "./utils/random"

async function createUserViaAdminUi(page: Page) {
  const email = randomEmail()
  const password = randomPassword()
  await page.goto("/admin")
  await page.getByRole("button", { name: "Add User" }).click()
  await page.getByPlaceholder("Email").fill(email)
  await page.getByPlaceholder("Password").first().fill(password)
  await page.getByPlaceholder("Password").last().fill(password)
  await page.getByRole("button", { name: "Save" }).click()
  await expect(page.getByText("User created successfully")).toBeVisible()
  return { email, password }
}

async function gotoPendingTab(page: Page) {
  await page.goto("/admin")
  await page.getByTestId("users-tab-pending-github").click()
  await expect(page.getByTestId("pending-github-logins")).toBeVisible()
}

async function uniqueProviderAccountId(): Promise<string> {
  return `${Date.now()}${Math.floor(Math.random() * 10_000)}`
}

test.describe.configure({ mode: "serial" })

test.describe("Admin Users page - pending GitHub flow", () => {
  test.beforeAll(async () => {
    await deleteAllPending()
  })

  test("pending requests appear in the Pending GitHub tab", async ({
    page,
  }) => {
    const providerAccountId = await uniqueProviderAccountId()
    await createPendingViaBridge({
      providerAccountId,
      providerLogin: "octo-pending",
      email: `${providerAccountId}@example.com`,
      fullName: "Octo Pending",
    })

    await gotoPendingTab(page)

    const row = page.getByTestId(`pending-row-${providerAccountId}`)
    await expect(row).toBeVisible()
    await expect(row).toContainText("octo-pending")
    await expect(row).toContainText(`${providerAccountId}@example.com`)
  })

  test("admin can deny a pending request", async ({ page }) => {
    const providerAccountId = await uniqueProviderAccountId()
    await createPendingViaBridge({
      providerAccountId,
      providerLogin: "octo-deny",
      email: `${providerAccountId}@example.com`,
    })

    await gotoPendingTab(page)
    await page.getByTestId(`pending-deny-${providerAccountId}`).click()
    await expect(page.getByText("Pending request denied")).toBeVisible()
    await expect(
      page.getByTestId(`pending-row-${providerAccountId}`),
    ).toHaveCount(0)
  })

  test("admin can approve by linking to an existing user", async ({ page }) => {
    const { email } = await createUserViaAdminUi(page)
    const providerAccountId = await uniqueProviderAccountId()
    await createPendingViaBridge({
      providerAccountId,
      providerLogin: "octo-link",
      email: `${providerAccountId}@example.com`,
    })

    await gotoPendingTab(page)
    await page.getByTestId(`pending-approve-${providerAccountId}`).click()

    const dialog = page.getByTestId("approve-pending-dialog")
    await expect(dialog).toBeVisible()
    await page.getByTestId("approve-mode-link").check()
    await page.getByTestId("approve-link-user-select").click()
    await page.getByTestId(`approve-link-user-${email}`).click()
    await page.getByTestId("approve-pending-submit").click()

    await expect(page.getByText("Pending request approved")).toBeVisible()
    await expect(
      page.getByTestId(`pending-row-${providerAccountId}`),
    ).toHaveCount(0)

    // Confirm user is linked by checking the Manage GitHub status dialog.
    await page.getByTestId("users-tab-users").click()
    const userRow = page.getByRole("row").filter({ hasText: email })
    await expect(userRow).toBeVisible()
    await userRow.getByRole("button").last().click()
    await page.getByRole("menuitem", { name: "Manage GitHub" }).click()
    await expect(page.getByTestId("github-link-status")).not.toContainText(
      /No GitHub account linked/i,
    )
  })

  test("admin can approve by creating a new user", async ({ page }) => {
    const providerAccountId = await uniqueProviderAccountId()
    const newEmail = `${providerAccountId}@example.com`
    await createPendingViaBridge({
      providerAccountId,
      providerLogin: "octo-create",
      email: newEmail,
      fullName: "Octo Create",
    })

    await gotoPendingTab(page)
    await page.getByTestId(`pending-approve-${providerAccountId}`).click()

    const dialog = page.getByTestId("approve-pending-dialog")
    await expect(dialog).toBeVisible()
    // create mode should be the default when email is present
    await page.getByTestId("approve-pending-submit").click()

    await expect(page.getByText("Pending request approved")).toBeVisible()
    await expect(
      page.getByTestId(`pending-row-${providerAccountId}`),
    ).toHaveCount(0)

    // The new user should now appear in the Users table with the GitHub badge.
    await page.getByTestId("users-tab-users").click()
    const userRow = page.getByRole("row").filter({ hasText: newEmail })
    await expect(userRow).toBeVisible()
    await expect(userRow.getByText("octo-create")).toBeVisible()
  })
})

test.describe("Admin Users page - simplified Manage GitHub", () => {
  test("only status + Unlink controls are exposed (no invite/manual link)", async ({
    page,
  }) => {
    const { email } = await createUserViaAdminUi(page)
    const userRow = page.getByRole("row").filter({ hasText: email })
    await userRow.getByRole("button").last().click()
    await page.getByRole("menuitem", { name: "Manage GitHub" }).click()

    await expect(page.getByTestId("github-link-status")).toContainText(
      /No GitHub account linked/i,
    )
    // Removed controls must not exist anymore.
    await expect(page.getByTestId("send-github-invite")).toHaveCount(0)
    await expect(page.getByTestId("github-provider-account-id")).toHaveCount(0)
    await expect(page.getByTestId("github-provider-login")).toHaveCount(0)
    await expect(page.getByTestId("link-github-submit")).toHaveCount(0)
  })
})
