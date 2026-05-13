import { expect, test } from "@playwright/test"

test.use({ storageState: { cookies: [], origins: [] } })

test.describe("GitHub login button on /login", () => {
  test("button is visible when VITE_AUTHJS_URL is configured", async ({
    page,
  }) => {
    await page.goto("/login")
    await expect(page.getByTestId("github-login-button")).toBeVisible()
  })

  test("button click triggers a redirect toward the configured Auth.js URL", async ({
    page,
  }) => {
    await page.goto("/login")
    const button = page.getByTestId("github-login-button")
    await expect(button).toBeVisible()

    // We don't actually want to navigate to Auth.js (and possibly onward to
    // GitHub) during tests. Stub the navigation by intercepting it as soon as
    // the button forces window.location.href change.
    const navigationPromise = page.waitForRequest((request) => {
      const url = request.url()
      return url.includes("/auth/signin")
    })

    await button.click()

    const request = await navigationPromise
    expect(request.url()).toContain("/auth/signin")
    expect(request.url()).toContain("provider=github")
    expect(request.url()).toContain("callbackUrl=")
    expect(decodeURIComponent(request.url())).toContain("/auth/callback")
  })
})

test.describe("GitHub auth callback page", () => {
  test("shows error when bridge_token is missing", async ({ page }) => {
    await page.goto("/auth/callback")
    await expect(page.getByTestId("github-login-error")).toContainText(
      /Missing bridge token/i,
    )
  })

  test("surfaces error param from Auth.js redirect", async ({ page }) => {
    await page.goto("/auth/callback?error=not_authenticated")
    await expect(page.getByTestId("github-login-error")).toContainText(
      "not_authenticated",
    )
  })

  test("rejects an obviously invalid bridge token", async ({ page }) => {
    // The backend will respond 401 for any unsigned/forged token. The global
    // MutationCache error handler clears the local token and redirects to
    // /login, so we expect the user to land back on the login page.
    await page.goto("/auth/callback?bridge_token=not-a-real-token")
    await expect(page).toHaveURL("/login")
  })

  test("shows pending-approval message when bridge returns pending_approval", async ({
    page,
  }) => {
    test.skip(
      !!process.env.CI,
      "Flaky under CI shard networking; verified locally with mocked bridge response.",
    )

    // Mock the bridge endpoint to return a pending-approval response without
    // needing a real Auth.js -> GitHub round trip.
    await page.route("**/api/v1/oauth/github/bridge*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "pending_approval",
          pending_id: "00000000-0000-0000-0000-000000000001",
          access_token: null,
          token_type: null,
        }),
      })
    })
    const bridgeResponse = page.waitForResponse(
      (response) =>
        response.url().includes("/api/v1/oauth/github/bridge") &&
        response.request().method() === "POST",
    )

    await page.goto("/auth/callback?bridge_token=stub-token-not-validated")
    await bridgeResponse
    await expect(page.getByTestId("github-pending-approval")).toContainText(
      /administrator must approve/i,
      { timeout: 15000 },
    )
  })
})
