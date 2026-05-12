// Instructor roster: mark verified complete, end session, grant via post-end badge wizard; trainee sees badges; revoke from wizard.
import { expect, test } from "@playwright/test"
import { getApiTokenAsSuperuser } from "./utils/bridgeToken"
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

    const token = await getApiTokenAsSuperuser()
    const auth = { Authorization: `Bearer ${token}` }
    const endRes = await request.post(
      `${apiBase}/api/v1/workshop/sessions/${session_id}/end`,
      { headers: auth },
    )
    expect(
      endRes.ok(),
      `end session failed: ${endRes.status()} ${await endRes.text()}`,
    ).toBeTruthy()

    await page.reload()
    await page.waitForLoadState("networkidle")
    await expect(page.getByTestId("workshop-ws-status")).toHaveText(
      /connected/i,
      { timeout: 15_000 },
    )

    await expect(
      page.getByTestId("workshop-post-end-badge-dialog"),
    ).toBeVisible({ timeout: 15_000 })

    await page
      .getByTestId(`workshop-roster-grant-badge-${participant.userId}`)
      .click()
    await expect(
      page.getByRole("button", { name: "Revoke E2E Grant Badge" }),
    ).toBeVisible({ timeout: 15_000 })

    await participantPage.reload()
    await participantPage.waitForLoadState("networkidle")
    await expect(
      participantPage.getByTestId(
        `workshop-trainee-session-badge-e2e-grant-${session_id}`,
      ),
    ).toBeVisible({ timeout: 30_000 })

    await page.getByRole("button", { name: "Revoke E2E Grant Badge" }).click()
    await page.getByTestId("workshop-roster-revoke-reason").fill("test revoke")
    await page.getByTestId("workshop-roster-revoke-confirm").click()
    await expect(page.getByTestId("workshop-roster-revoke-reason")).toBeHidden({
      timeout: 15_000,
    })

    await participantPage.reload()
    await participantPage.waitForLoadState("networkidle")
    await expect(
      participantPage.getByTestId(
        `workshop-trainee-session-badge-e2e-grant-${session_id}`,
      ),
    ).toHaveCount(0)

    await participantContext.close()
  })

  test("instructor acknowledges lesson sync drift after bump", async ({
    page,
    request,
  }) => {
    const bootstrap = await request.post(
      `${apiBase}/api/v1/private/workshop/e2e-live-session/`,
    )
    expect(bootstrap.ok()).toBeTruthy()
    const { session_id } = await bootstrap.json()

    await page.goto(`/workshop/${session_id}`)
    await page.waitForLoadState("networkidle")
    await expect(page.getByTestId("workshop-ws-status")).toHaveText(
      /connected/i,
      { timeout: 15_000 },
    )

    const bump = await request.post(
      `${apiBase}/api/v1/private/workshop/e2e-bump-lesson-sync/${session_id}/`,
    )
    expect(bump.ok()).toBeTruthy()

    await page.reload()
    await page.waitForLoadState("networkidle")
    await expect(
      page.getByTestId("workshop-lesson-sync-drift-alert"),
    ).toBeVisible({ timeout: 15_000 })
    await page.getByTestId("workshop-lesson-sync-drift-open-dialog").click()
    await page.getByTestId("workshop-lesson-sync-drift-switch-latest").click()
    await expect(
      page.getByTestId("workshop-lesson-sync-drift-alert"),
    ).toBeHidden({ timeout: 15_000 })
  })
})
