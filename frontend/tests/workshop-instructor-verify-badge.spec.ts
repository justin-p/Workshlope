// Instructor verifies trainee, ends session for auto badge award; hub recipients revoke + re-grant; trainee sees badges on the session page.
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

  test("instructor verifies trainee, ends session for auto badge; hub revoke and re-grant", async ({
    browser,
    page,
    request,
  }) => {
    test.setTimeout(120_000)
    const participant = await createParticipantUserForWorkshop()
    const bootstrap = await request.post(
      `${apiBase}/api/v1/private/workshop/e2e-live-session/?participant_email=${encodeURIComponent(participant.email)}&with_e2e_badge=true`,
    )
    expect(bootstrap.ok()).toBeTruthy()
    const { session_id } = (await bootstrap.json()) as { session_id: string }

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

    await page.getByTestId("workshop-instructor-end").click()
    await expect(
      page.getByTestId("workshop-post-end-badge-preview-dialog"),
    ).toBeVisible({ timeout: 15_000 })
    await page.getByTestId("workshop-post-end-badge-preview-close").click()
    await expect(
      page.getByTestId("workshop-post-end-badge-preview-dialog"),
    ).toBeHidden({ timeout: 10_000 })

    const badgeSlug = `e2e-grant-${session_id}`
    await participantPage.reload()
    await participantPage.waitForLoadState("networkidle")
    await expect(
      participantPage.getByTestId(
        `workshop-trainee-session-badge-${badgeSlug}`,
      ),
    ).toBeVisible({ timeout: 30_000 })

    await page.goto("/workshop/badges")
    await page.waitForLoadState("networkidle")
    await page
      .getByTestId(`workshop-badge-hub-recipients-open-${badgeSlug}`)
      .click()
    await expect(
      page.getByTestId("workshop-badge-recipients-dialog"),
    ).toBeVisible({ timeout: 15_000 })
    await page
      .getByTestId(`workshop-badge-hub-recipient-revoke-${participant.userId}`)
      .click()
    await page
      .getByTestId("workshop-badge-hub-recipients-reason")
      .fill("test revoke")
    await page
      .getByTestId("workshop-badge-hub-recipients-revoke-confirm")
      .click()
    await expect(
      page.getByTestId("workshop-badge-hub-recipients-revoke-panel"),
    ).toBeHidden({ timeout: 15_000 })

    await participantPage.reload()
    await participantPage.waitForLoadState("networkidle")
    await expect(
      participantPage.getByTestId(
        `workshop-trainee-session-badge-${badgeSlug}`,
      ),
    ).toHaveCount(0)

    await page.getByTestId("workshop-badge-recipients-close").click()
    await page.getByTestId(`workshop-badge-hub-grant-open-${badgeSlug}`).click()
    await expect(page.getByTestId("workshop-badge-grant-dialog")).toBeVisible({
      timeout: 10_000,
    })
    await page
      .getByTestId("workshop-badge-grant-search")
      .fill(participant.email)
    await expect(
      page.getByTestId(`workshop-badge-grant-user-row-${participant.userId}`),
    ).toBeVisible({ timeout: 15_000 })
    await page
      .getByTestId(`workshop-badge-grant-user-row-${participant.userId}`)
      .click()
    await page.getByTestId("workshop-badge-grant-confirm").click()
    await expect(page.getByTestId("workshop-badge-grant-dialog")).toBeHidden({
      timeout: 15_000,
    })

    await participantPage.reload()
    await participantPage.waitForLoadState("networkidle")
    await expect(
      participantPage.getByTestId(
        `workshop-trainee-session-badge-${badgeSlug}`,
      ),
    ).toBeVisible({ timeout: 30_000 })

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
    const { session_id } = (await bootstrap.json()) as { session_id: string }

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
