// Trainee read-only lesson review after session ended: multi-part nav and softened pre-work.
import { expect, test } from "@playwright/test"
import { createUser } from "./utils/privateApi"
import { randomEmail } from "./utils/random"

const apiBase = process.env.VITE_API_URL ?? "http://localhost:8000"

test.describe("Workshop post-session read-only", () => {
  test("trainee browses all parts on an ended session; incomplete pre-work is non-blocking", async ({
    page,
    request,
  }) => {
    const email = randomEmail()
    const password = "changethis123"
    await createUser({
      email,
      password,
    })
    const bootstrap = await request.post(
      `${apiBase}/api/v1/private/workshop/e2e-live-session/?initial_status=ended&participant_email=${encodeURIComponent(email)}&with_incomplete_required_prerequisite=true`,
    )
    expect(bootstrap.ok()).toBeTruthy()
    const { session_id } = await bootstrap.json()

    await page.goto("/login")
    await page.getByTestId("email-input").fill(email)
    await page.getByTestId("password-input").fill(password)
    await page.getByRole("button", { name: "Log In" }).click()
    await page.waitForURL(/\/dashboard\/(trainee|instructor|admin)/)
    await page.goto(`/workshop/${session_id}`)
    await page.waitForLoadState("networkidle")

    await expect(
      page.getByTestId("workshop-read-only-session-banner"),
    ).toBeVisible({ timeout: 15_000 })
    await expect(page.getByTestId("workshop-ws-status")).toContainText(
      /read-only/i,
    )
    await expect(page.getByTestId("workshop-prework-header-count")).toHaveCount(
      0,
    )

    const partBody = page.getByTestId("workshop-current-part-body")
    await expect(partBody).toContainText("Part 0", { timeout: 15_000 })
    await expect(partBody).toContainText("echo hi")

    await expect(
      page.getByRole("button", { name: /copy code/i }).first(),
    ).toBeVisible()

    const preworkBanner = page.getByTestId(
      "workshop-prework-participant-banner",
    )
    await expect(preworkBanner).toBeVisible({ timeout: 15_000 })
    await expect(preworkBanner).toContainText(/does not block reading/i)

    await page.getByTestId("workshop-read-only-part-next").click()
    await expect(partBody).toContainText("Part 1")

    await page.getByTestId("workshop-read-only-part-prev").click()
    await expect(partBody).toContainText("Part 0")
  })
})
