import { expect, test } from "@playwright/test"
import { createUser } from "./utils/privateApi"
import { randomEmail } from "./utils/random"

const apiBase = process.env.VITE_API_URL ?? "http://localhost:8000"

async function createParticipantUserForWorkshop() {
  const email = randomEmail()
  const password = "changethis123"
  await createUser({
    email,
    password,
  })
  return { email, password }
}

test.describe("Workshop live session", () => {
  // Same-process workshop hub + nginx WS proxy: parallel tests caused intermittent
  // "connecting" forever (participant never received session.connected). Run in order.
  test.describe.configure({ mode: "serial" })

  test("participant is gated until required pre-work is complete", async ({
    browser,
    request,
  }) => {
    const participant = await createParticipantUserForWorkshop()
    const br = await request.post(
      `${apiBase}/api/v1/private/workshop/e2e-live-session/?with_incomplete_required_prerequisite=true&participant_email=${encodeURIComponent(participant.email)}`,
    )
    expect(br.ok()).toBeTruthy()
    const { session_id } = await br.json()

    const participantContext = await browser.newContext({
      storageState: { cookies: [], origins: [] },
    })
    const participantPage = await participantContext.newPage()
    await participantPage.goto("/login")
    await participantPage.getByTestId("email-input").fill(participant.email)
    await participantPage
      .getByTestId("password-input")
      .fill(participant.password)
    await participantPage.getByRole("button", { name: "Log In" }).click()
    await participantPage.waitForURL(/\/dashboard\/(trainee|instructor|admin)/)

    await participantPage.goto(`/workshop/${session_id}`)
    await expect(participantPage.getByTestId("workshop-ws-status")).toHaveText(
      /gated/i,
      {
        timeout: 15_000,
      },
    )
    await expect(
      participantPage.getByTestId("workshop-prework-gate-error"),
    ).toContainText("Pre-work required before joining live session")
    await expect(
      participantPage.getByTestId("workshop-prework-gate-error"),
    ).toContainText("Complete all required prerequisites")
    await expect(participantPage.getByTestId("workshop-error")).toHaveCount(0)
    await expect(
      participantPage.getByTestId("workshop-prework-header-count"),
    ).toContainText("Required pre-work remaining: 1")
    const banner = participantPage.getByTestId(
      "workshop-prework-participant-banner",
    )
    await expect(banner).toBeVisible({ timeout: 15_000 })
    await participantPage.getByTestId("workshop-prework-mark-complete").click()
    await expect(banner).toHaveCount(0, { timeout: 15_000 })
    await participantPage.reload()
    await expect(participantPage.getByTestId("workshop-ws-status")).toHaveText(
      /connected/i,
      {
        timeout: 15_000,
      },
    )
    await participantContext.close()
  })

  test("participant view connects WebSocket after enter + ticket", async ({
    page,
    request,
  }) => {
    const br = await request.post(
      `${apiBase}/api/v1/private/workshop/e2e-live-session/`,
    )
    expect(br.ok()).toBeTruthy()
    const body = await br.json()
    expect(body).toHaveProperty("session_id")

    await page.goto(`/workshop/${body.session_id}`)
    await expect(page.getByTestId("workshop-ws-status")).toHaveText(
      /connected/i,
      {
        timeout: 15_000,
      },
    )
  })

  test("live_status buttons send trainee signals when connected", async ({
    page,
    request,
  }) => {
    const br = await request.post(
      `${apiBase}/api/v1/private/workshop/e2e-live-session/`,
    )
    expect(br.ok()).toBeTruthy()
    const { session_id } = await br.json()

    await page.goto(`/workshop/${session_id}`)
    await expect(page.getByTestId("workshop-ws-status")).toHaveText(
      /connected/i,
      { timeout: 15_000 },
    )

    await page.getByRole("button", { name: "Mark done" }).click()
    await expect(page.getByTestId("workshop-ws-last-ack")).toContainText(
      "live_status.ack",
    )
    await expect(page.getByTestId("workshop-ws-last-raw")).not.toContainText(
      "participant.live_status",
    )
  })

  test("instructor-only bootstrap: pause, resume, and advance ack without enter", async ({
    page,
    request,
  }) => {
    const br = await request.post(
      `${apiBase}/api/v1/private/workshop/e2e-live-session/?omit_participant_seat=true`,
    )
    expect(br.ok()).toBeTruthy()
    const { session_id } = await br.json()

    await page.goto(`/workshop/${session_id}`)
    await expect(page.getByTestId("workshop-ws-status")).toHaveText(
      /connected/i,
      { timeout: 15_000 },
    )
    await expect(
      page.getByTestId("workshop-prework-header-count"),
    ).toContainText("Roster trainees blocked by required pre-work: 0")
    await expect(page.getByRole("button", { name: "Mark done" })).toHaveCount(0)

    await expect(page.getByTestId("workshop-timer-start")).toContainText(
      "Start 5m countdown",
    )
    await page.getByTestId("workshop-timer-start").click()
    await expect(page.getByTestId("workshop-timer-status")).toContainText(
      "running",
    )
    await expect(page.getByTestId("workshop-timer-status")).toContainText(
      /Timer: running( \(\d+:\d{2} left\))?/,
    )
    await page.getByTestId("workshop-timer-pause").click()
    await expect(page.getByTestId("workshop-timer-status")).toContainText(
      "paused",
    )
    await page.getByTestId("workshop-timer-resume").click()
    await expect(page.getByTestId("workshop-timer-status")).toContainText(
      "running",
    )
    await page.getByTestId("workshop-timer-stop").click()
    await expect(page.getByTestId("workshop-timer-status")).toContainText(
      "inactive",
    )

    await page.getByTestId("workshop-instructor-pause").click()
    await expect(page.getByTestId("workshop-ws-last-ack")).toContainText(
      "session.pause.ack",
    )

    await page.getByTestId("workshop-instructor-resume").click()
    await expect(page.getByTestId("workshop-ws-last-ack")).toContainText(
      "session.resume.ack",
    )

    await page.getByTestId("workshop-instructor-advance").click()
    await expect(page.getByTestId("workshop-ws-last-ack")).toContainText(
      "part.advance.ack",
    )

    await page.getByTestId("workshop-instructor-end").click()
    await expect(page.getByTestId("workshop-ws-last-raw")).toContainText(
      '"status":"ended"',
    )
    await expect(page.getByTestId("workshop-instructor-end")).toBeDisabled()
  })

  test("participant live_status fan-out is instructor-only", async ({
    page,
    browser,
    request,
  }) => {
    const participant = await createParticipantUserForWorkshop()
    const br = await request.post(
      `${apiBase}/api/v1/private/workshop/e2e-live-session/?participant_email=${encodeURIComponent(participant.email)}`,
    )
    expect(br.ok()).toBeTruthy()
    const { session_id } = await br.json()

    const participantContext = await browser.newContext({
      storageState: { cookies: [], origins: [] },
    })
    const participantPage = await participantContext.newPage()
    await participantPage.goto("/login")
    await participantPage.getByTestId("email-input").fill(participant.email)
    await participantPage
      .getByTestId("password-input")
      .fill(participant.password)
    await participantPage.getByRole("button", { name: "Log In" }).click()
    await participantPage.waitForURL(/\/dashboard\/(trainee|instructor|admin)/)
    await participantPage.waitForFunction(() =>
      Boolean(window.localStorage.getItem("access_token")),
    )

    await page.goto(`/workshop/${session_id}`)
    await expect(page.getByTestId("workshop-ws-status")).toHaveText(
      /connected/i,
      {
        timeout: 15_000,
      },
    )

    await participantPage.goto(`/workshop/${session_id}`)
    const wsStatus = participantPage.getByTestId("workshop-ws-status")
    await wsStatus.waitFor({ state: "visible" })
    await expect(wsStatus).toHaveText(/connected/i, { timeout: 20_000 })

    await participantPage.getByRole("button", { name: "Mark done" }).click()
    await expect(
      participantPage.getByTestId("workshop-ws-last-ack"),
    ).toContainText("live_status.ack")
    await expect(
      participantPage.getByTestId("workshop-ws-last-raw"),
    ).not.toContainText("participant.live_status")
    await expect(page.getByTestId("workshop-ws-last-raw")).toContainText(
      "participant.live_status",
    )

    await participantContext.close()
  })

  test("scheduled session can be started from instructor page", async ({
    page,
    request,
  }) => {
    const br = await request.post(
      `${apiBase}/api/v1/private/workshop/e2e-live-session/?omit_participant_seat=true&initial_status=scheduled`,
    )
    expect(br.ok()).toBeTruthy()
    const { session_id } = await br.json()

    await page.goto(`/workshop/${session_id}`)
    await expect(page.getByTestId("workshop-error")).toContainText(
      "Session not started yet",
    )
    await page.getByTestId("workshop-instructor-start").click()
    await expect(page.getByTestId("workshop-ws-status")).toHaveText(
      /connected/i,
      { timeout: 15_000 },
    )
  })

  test("workshops hub shows blocked pre-work count on cards", async ({
    page,
    request,
  }) => {
    const br = await request.post(
      `${apiBase}/api/v1/private/workshop/e2e-live-session/?with_incomplete_required_prerequisite=true`,
    )
    expect(br.ok()).toBeTruthy()
    const { session_id } = await br.json()

    await page.goto("/workshops")
    await expect(
      page.getByTestId(`workshop-card-blocked-count-${session_id}`),
    ).toContainText("Blocked: 1")
    await expect(
      page.getByTestId("workshop-cards-total-blocked"),
    ).toContainText("Total blocked trainees: 1")
    await expect(page.getByTestId("workshop-blocked-drilldown")).toContainText(
      "Blocked sessions",
    )
    await expect(page.getByTestId("workshop-blocked-drilldown")).toContainText(
      "1 blocked",
    )
    await expect(page.getByTestId("workshop-blocked-drilldown")).toContainText(
      "Open",
    )
    await page.getByTestId("workshop-cards-blocked-only-toggle").click()
    await expect(
      page.getByTestId("workshop-cards-blocked-only-toggle"),
    ).toContainText("Show all sessions")
  })
})
