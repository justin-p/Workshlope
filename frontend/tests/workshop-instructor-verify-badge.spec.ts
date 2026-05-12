// Instructor roster: mark verified complete, grant session badge; trainee sees badges after reload.
import { expect, test } from "@playwright/test"
import { createUser } from "./utils/privateApi"
import { randomEmail } from "./utils/random"

const apiBase = process.env.VITE_API_URL ?? "http://localhost:8000"

async function createParticipantUserForWorkshop() {
  const email = randomEmail()
  const password = "changethis123"
  const created = await createUser({ email, password })
  return { email, password, userId: created.id }
}

async function loginTrainee(
  participantPage: import("@playwright/test").Page,
  email: string,
  password: string,
) {
  await participantPage.goto("/login")
  await participantPage.getByTestId("email-input").fill(email)
  await participantPage.getByTestId("password-input").fill(password)
  await participantPage.getByRole("button", { name: "Log In" }).click()
  await participantPage.waitForURL(/\/dashboard\/(trainee|instructor|admin)/)
}

test.describe("Workshop instructor verify and badge grant", () => {
  test.describe.configure({ mode: "serial" })

  test("instructor verifies trainee then grants badge; trainee sees badge", async ({
    browser,
    page,
    request,
  }) => {
    const participant = await createParticipantUserForWorkshop()
    const bootstrap = await request.post(
      `${apiBase}/api/v1/private/workshop/e2e-live-session/?participant_email=${encodeURIComponent(participant.email)}&with_e2e_badge=true`,
    )
    expect(bootstrap.ok()).toBeTruthy()
    const { session_id } = await bootstrap.json()

    const participantContext = await browser.newContext({
      storageState: { cookies: [], origins: [] },
    })
    const participantPage = await participantContext.newPage()
    await loginTrainee(participantPage, participant.email, participant.password)
    await participantPage.goto(`/workshop/${session_id}`)
    await participantPage.waitForLoadState("networkidle")
    await expect(participantPage.getByTestId("workshop-ws-status")).toHaveText(
      /connected/i,
      { timeout: 20_000 },
    )

    await page.goto(`/workshop/${session_id}`)
    await expect(page.getByTestId("workshop-ws-status")).toHaveText(
      /connected/i,
      { timeout: 15_000 },
    )

    await page
      .getByTestId(`workshop-roster-verify-complete-${participant.userId}`)
      .click()
    await expect(
      page.getByTestId(`workshop-roster-verified-label-${participant.userId}`),
    ).toBeVisible({ timeout: 10_000 })

    await page
      .getByTestId(`workshop-roster-grant-badge-${participant.userId}`)
      .click()

    await participantPage.reload()
    await participantPage.waitForLoadState("networkidle")
    await expect(
      participantPage.getByTestId(
        `workshop-trainee-session-badge-e2e-grant-${session_id}`,
      ),
    ).toBeVisible({ timeout: 15_000 })

    await participantContext.close()
  })
})
