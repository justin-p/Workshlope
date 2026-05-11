import { expect, test } from "@playwright/test"
import { createUser } from "./utils/privateApi"
import { randomEmail } from "./utils/random"

const apiBase = process.env.VITE_API_URL ?? "http://localhost:8000"

async function createParticipantUserForWorkshop() {
  const email = randomEmail()
  const password = "changethis123"
  const created = await createUser({
    email,
    password,
  })
  return { email, password, userId: created.id }
}

test.describe("Workshop live session", () => {
  // Same-process workshop hub + nginx WS proxy: parallel tests caused intermittent
  // "connecting" forever (participant never received session.connected). Run in order.
  test.describe.configure({ mode: "serial" })

  test("instructor-led flow covers trainee gate, progression, and closeout", async ({
    browser,
    page,
    request,
  }) => {
    const participant = await createParticipantUserForWorkshop()
    const bootstrap = await request.post(
      `${apiBase}/api/v1/private/workshop/e2e-live-session/?with_incomplete_required_prerequisite=true&participant_email=${encodeURIComponent(participant.email)}`,
    )
    expect(bootstrap.ok()).toBeTruthy()
    const { session_id } = await bootstrap.json()

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

    await page.goto(`/workshop/${session_id}`)
    await expect(
      page.getByTestId("workshop-instructor-back-part"),
    ).toBeDisabled()
    await expect(page.getByTestId("workshop-ws-status")).toHaveText(
      /connected/i,
      {
        timeout: 15_000,
      },
    )

    await participantPage.goto(`/workshop/${session_id}`)
    await expect(participantPage.getByTestId("workshop-ws-status")).toHaveText(
      /gated/i,
      { timeout: 15_000 },
    )
    const preworkBanner = participantPage.getByTestId(
      "workshop-prework-participant-banner",
    )
    await expect(preworkBanner).toBeVisible({ timeout: 15_000 })
    await participantPage.getByTestId("workshop-prework-mark-complete").click()
    await expect(preworkBanner).toHaveCount(0, { timeout: 15_000 })
    await participantPage.reload()
    await expect(participantPage.getByTestId("workshop-ws-status")).toHaveText(
      /connected/i,
      { timeout: 15_000 },
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
    await page.getByTestId("workshop-instructor-back-part").click()
    await expect(page.getByTestId("workshop-ws-last-ack")).toContainText(
      "part.advance.ack",
    )
    await expect(page.getByTestId("workshop-instructor-advance")).toBeEnabled()

    await page.getByTestId("workshop-instructor-end").click()
    await expect(page.getByTestId("workshop-ws-last-raw")).toContainText(
      '"status":"ended"',
    )
    await expect(
      participantPage.getByTestId("workshop-ws-last-raw"),
    ).toContainText('"status":"ended"')

    await participantContext.close()
  })

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
    const participant = await createParticipantUserForWorkshop()
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
    await expect(page.getByTestId("workshop-roster-empty")).toBeVisible()
    await page
      .getByTestId("workshop-add-trainee-user-id")
      .fill(participant.userId)
    await page.getByTestId("workshop-add-trainee-submit").click()
    await expect(page.getByTestId("workshop-roster-list")).toContainText(
      participant.email,
    )

    await expect(page.getByTestId("workshop-timer-start")).toContainText(
      "Start part countdown",
    )
    await page.getByTestId("workshop-timer-start").click()
    await expect(page.getByTestId("workshop-timer-status")).toContainText(
      "running",
    )
    await expect(page.getByTestId("workshop-timer-status")).toContainText(
      /Timer: running( \(\d+:\d{2} left\))?/,
    )
    await expect(page.getByTestId("workshop-timer-events")).toContainText(
      /(\d{2}:\d{2}|No timer actions recorded yet\.)/,
    )
    await page.getByTestId("workshop-timer-extend-minutes").fill("2")
    await page.getByTestId("workshop-timer-extend").click()
    await expect(page.getByTestId("workshop-timer-events")).toContainText(
      "extend",
    )
    await page.getByTestId("workshop-timer-pause").click()
    await expect(page.getByTestId("workshop-timer-status")).toContainText(
      "paused",
    )
    await page.getByTestId("workshop-timer-resume").click()
    await expect(page.getByTestId("workshop-timer-status")).toContainText(
      "running",
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
    await expect(page.getByTestId("workshop-timer-status")).toContainText(
      "inactive",
    )
    await page.getByTestId("workshop-timer-start").click()
    await expect(page.getByTestId("workshop-timer-status")).toContainText(
      "running",
    )
    await page.getByTestId("workshop-timer-stop").click()
    await expect(page.getByTestId("workshop-timer-status")).toContainText(
      "inactive",
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

    await expect(
      page.getByTestId(`workshop-roster-live-status-${participant.userId}`),
    ).toHaveText("done", { timeout: 10_000 })

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
    await expect(page.getByTestId("workshop-session-lobby")).toBeVisible()
    await expect(page.getByTestId("workshop-current-part")).toHaveCount(0)
    await expect(page.getByTestId("workshop-ws-status")).toHaveText(
      /waiting for start/i,
    )
    await expect(page.getByTestId("workshop-error")).toHaveCount(0)

    await page.getByTestId("workshop-instructor-start").click()
    await expect(page.getByTestId("workshop-ws-status")).toHaveText(
      /connected/i,
      { timeout: 15_000 },
    )
  })

  test("shows fallback banner when lesson repo health is degraded", async ({
    page,
    request,
  }) => {
    const br = await request.post(
      `${apiBase}/api/v1/private/workshop/e2e-live-session/?omit_participant_seat=true`,
    )
    expect(br.ok()).toBeTruthy()
    const { session_id } = await br.json()

    await page.route("**/api/v1/workshop/sessions/*", async (route) => {
      const req = route.request()
      if (
        req.method() !== "GET" ||
        !/\/api\/v1\/workshop\/sessions\/[^/]+$/.test(req.url())
      ) {
        await route.continue()
        return
      }

      const upstream = await route.fetch()
      const body = (await upstream.json()) as {
        lesson?: Record<string, unknown>
      }
      body.lesson = {
        ...(body.lesson ?? {}),
        lesson_repo_health: "unhealthy",
      }
      await route.fulfill({
        response: upstream,
        body: JSON.stringify(body),
        headers: {
          ...upstream.headers(),
          "content-type": "application/json",
        },
      })
    })

    await page.goto(`/workshop/${session_id}`)
    await expect(
      page.getByTestId("workshop-lesson-source-warning"),
    ).toContainText("Source sync is currently degraded")
  })

  test("shows blocking banner when lesson content is unavailable", async ({
    page,
    request,
  }) => {
    const br = await request.post(
      `${apiBase}/api/v1/private/workshop/e2e-live-session/?omit_participant_seat=true`,
    )
    expect(br.ok()).toBeTruthy()
    const { session_id } = await br.json()

    await page.route("**/api/v1/workshop/sessions/*", async (route) => {
      const req = route.request()
      if (
        req.method() !== "GET" ||
        !/\/api\/v1\/workshop\/sessions\/[^/]+$/.test(req.url())
      ) {
        await route.continue()
        return
      }

      const upstream = await route.fetch()
      const body = (await upstream.json()) as {
        lesson?: Record<string, unknown>
        parts?: unknown[]
      }
      body.lesson = {
        ...(body.lesson ?? {}),
        lesson_content_available: false,
        lesson_content_issue: "no_parts_synced",
      }
      body.parts = []
      await route.fulfill({
        response: upstream,
        body: JSON.stringify(body),
        headers: {
          ...upstream.headers(),
          "content-type": "application/json",
        },
      })
    })

    await page.goto(`/workshop/${session_id}`)
    await expect(
      page.getByTestId("workshop-lesson-content-unavailable"),
    ).toContainText("No lesson parts are currently synced for this lesson")
    await expect(page.getByTestId("workshop-current-part")).toHaveCount(0)
    await expect(page.getByTestId("workshop-instructor-pause")).toBeDisabled()
    await expect(page.getByTestId("workshop-instructor-resume")).toBeDisabled()
    await expect(page.getByTestId("workshop-instructor-advance")).toBeDisabled()
    await expect(page.getByTestId("workshop-instructor-end")).toBeDisabled()
    await expect(page.getByTestId("workshop-timer-start")).toBeDisabled()
  })

  test("shows missing lesson hint when session lesson record is unavailable", async ({
    page,
    request,
  }) => {
    const br = await request.post(
      `${apiBase}/api/v1/private/workshop/e2e-live-session/?omit_participant_seat=true`,
    )
    expect(br.ok()).toBeTruthy()
    const { session_id } = await br.json()

    await page.route("**/api/v1/workshop/sessions/*", async (route) => {
      const req = route.request()
      if (
        req.method() !== "GET" ||
        !/\/api\/v1\/workshop\/sessions\/[^/]+$/.test(req.url())
      ) {
        await route.continue()
        return
      }

      const upstream = await route.fetch()
      const body = (await upstream.json()) as {
        lesson?: Record<string, unknown>
        parts?: unknown[]
      }
      body.lesson = {
        ...(body.lesson ?? {}),
        lesson_content_available: false,
        lesson_content_issue: "lesson_missing",
      }
      body.parts = []
      await route.fulfill({
        response: upstream,
        body: JSON.stringify(body),
        headers: {
          ...upstream.headers(),
          "content-type": "application/json",
        },
      })
    })

    await page.goto(`/workshop/${session_id}`)
    await expect(
      page.getByTestId("workshop-lesson-content-unavailable"),
    ).toContainText("lesson record that no longer exists")
    await expect(
      page.getByTestId("workshop-lesson-content-unavailable"),
    ).toContainText("(lesson_missing)")
  })

  test("shows missing repo hint when lesson repository record is unavailable", async ({
    page,
    request,
  }) => {
    const br = await request.post(
      `${apiBase}/api/v1/private/workshop/e2e-live-session/?omit_participant_seat=true`,
    )
    expect(br.ok()).toBeTruthy()
    const { session_id } = await br.json()

    await page.route("**/api/v1/workshop/sessions/*", async (route) => {
      const req = route.request()
      if (
        req.method() !== "GET" ||
        !/\/api\/v1\/workshop\/sessions\/[^/]+$/.test(req.url())
      ) {
        await route.continue()
        return
      }

      const upstream = await route.fetch()
      const body = (await upstream.json()) as {
        lesson?: Record<string, unknown>
        parts?: unknown[]
      }
      body.lesson = {
        ...(body.lesson ?? {}),
        lesson_content_available: false,
        lesson_content_issue: "lesson_repo_missing",
      }
      body.parts = []
      await route.fulfill({
        response: upstream,
        body: JSON.stringify(body),
        headers: {
          ...upstream.headers(),
          "content-type": "application/json",
        },
      })
    })

    await page.goto(`/workshop/${session_id}`)
    await expect(
      page.getByTestId("workshop-lesson-content-unavailable"),
    ).toContainText("source repository record is missing")
    await expect(
      page.getByTestId("workshop-lesson-content-unavailable"),
    ).toContainText("(lesson_repo_missing)")
  })

  test("can retry lesson check and resume controls after content recovers", async ({
    page,
    request,
  }) => {
    const br = await request.post(
      `${apiBase}/api/v1/private/workshop/e2e-live-session/?omit_participant_seat=true`,
    )
    expect(br.ok()).toBeTruthy()
    const { session_id } = await br.json()
    let detailRequests = 0

    await page.route("**/api/v1/workshop/sessions/*", async (route) => {
      const req = route.request()
      if (
        req.method() !== "GET" ||
        !/\/api\/v1\/workshop\/sessions\/[^/]+$/.test(req.url())
      ) {
        await route.continue()
        return
      }

      detailRequests += 1
      const upstream = await route.fetch()
      const body = (await upstream.json()) as {
        lesson?: Record<string, unknown>
        parts?: unknown[]
      }

      if (detailRequests === 1) {
        body.lesson = {
          ...(body.lesson ?? {}),
          lesson_content_available: false,
          lesson_content_issue: "no_parts_synced",
        }
        body.parts = []
      }

      await route.fulfill({
        response: upstream,
        body: JSON.stringify(body),
        headers: {
          ...upstream.headers(),
          "content-type": "application/json",
        },
      })
    })

    await page.goto(`/workshop/${session_id}`)
    await expect(
      page.getByTestId("workshop-lesson-content-unavailable"),
    ).toBeVisible()
    await expect(page.getByTestId("workshop-instructor-advance")).toBeDisabled()

    await page.getByTestId("workshop-lesson-content-refresh").click()
    await expect(
      page.getByTestId("workshop-lesson-content-unavailable"),
    ).toHaveCount(0)
    await expect(page.getByTestId("workshop-instructor-advance")).toBeEnabled()
  })

  test("auto-recovers lesson banner when detail polling sees content return", async ({
    page,
    request,
  }) => {
    const br = await request.post(
      `${apiBase}/api/v1/private/workshop/e2e-live-session/?omit_participant_seat=true`,
    )
    expect(br.ok()).toBeTruthy()
    const { session_id } = await br.json()
    let detailRequests = 0

    await page.route("**/api/v1/workshop/sessions/*", async (route) => {
      const req = route.request()
      if (
        req.method() !== "GET" ||
        !/\/api\/v1\/workshop\/sessions\/[^/]+$/.test(req.url())
      ) {
        await route.continue()
        return
      }

      detailRequests += 1
      const upstream = await route.fetch()
      const body = (await upstream.json()) as {
        lesson?: Record<string, unknown>
        parts?: unknown[]
      }

      if (detailRequests === 1) {
        body.lesson = {
          ...(body.lesson ?? {}),
          lesson_content_available: false,
          lesson_content_issue: "no_parts_synced",
        }
        body.parts = []
      }

      await route.fulfill({
        response: upstream,
        body: JSON.stringify(body),
        headers: {
          ...upstream.headers(),
          "content-type": "application/json",
        },
      })
    })

    await page.goto(`/workshop/${session_id}`)
    await expect(
      page.getByTestId("workshop-lesson-content-unavailable"),
    ).toBeVisible()
    await expect(page.getByTestId("workshop-instructor-advance")).toBeDisabled()

    await expect(
      page.getByTestId("workshop-lesson-content-unavailable"),
    ).toHaveCount(0, {
      timeout: 15_000,
    })
    await expect(page.getByTestId("workshop-instructor-advance")).toBeEnabled()
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
    const totalBlockedText = await page
      .getByTestId("workshop-cards-total-blocked")
      .innerText()
    const totalBlockedCount = Number.parseInt(
      totalBlockedText.replace(/^\D+/u, ""),
      10,
    )
    expect(totalBlockedCount).toBeGreaterThanOrEqual(1)
    await expect(page.getByTestId("workshop-blocked-drilldown")).toContainText(
      "Blocked sessions",
    )
    await expect(page.getByTestId("workshop-blocked-drilldown")).toContainText(
      "1 blocked",
    )
    await expect(page.getByTestId("workshop-blocked-drilldown")).toContainText(
      "Open",
    )
    await expect(page.getByTestId("workshop-blocked-analytics")).toContainText(
      "Blocked prerequisite analytics",
    )
    await expect(
      page.getByTestId("workshop-blocked-analytics-ratio"),
    ).toContainText("Sessions impacted:")
    await expect(
      page.getByTestId("workshop-blocked-analytics-most-blocked"),
    ).toContainText("Most blocked session:")
    await page.getByTestId("workshop-cards-blocked-only-toggle").click()
    await expect(
      page.getByTestId("workshop-cards-blocked-only-toggle"),
    ).toContainText("Show all sessions")
  })

  test("instructor session view shows prerequisite roster analytics", async ({
    page,
    request,
  }) => {
    const br = await request.post(
      `${apiBase}/api/v1/private/workshop/e2e-live-session/?with_incomplete_required_prerequisite=true&omit_participant_seat=true`,
    )
    expect(br.ok()).toBeTruthy()
    const { session_id } = await br.json()

    await page.goto(`/workshop/${session_id}`)
    await expect(page.getByTestId("workshop-ws-status")).toHaveText(
      /connected/i,
      {
        timeout: 15_000,
      },
    )

    const panel = page.getByTestId("workshop-prework-instructor-panel")
    await expect(panel).toBeVisible()
    await expect(
      page.getByTestId("workshop-prework-instructor-gaps-count"),
    ).toContainText(/trainee\(s\) still missing/i)
    await expect(panel).toContainText(/trainees done/i)
  })

  test("workshops hub redirects non-instructors to trainee dashboard", async ({
    browser,
  }) => {
    const participant = await createParticipantUserForWorkshop()
    const participantContext = await browser.newContext({
      storageState: { cookies: [], origins: [] },
    })
    const page = await participantContext.newPage()

    await page.goto("/login")
    await page.getByTestId("email-input").fill(participant.email)
    await page.getByTestId("password-input").fill(participant.password)
    await page.getByRole("button", { name: "Log In" }).click()
    await page.waitForURL("/dashboard/trainee")

    await page.goto("/workshops")
    await page.waitForURL("/dashboard/trainee")
    await expect(
      page.getByTestId("workshop-lesson-repo-sync-card"),
    ).toHaveCount(0)

    await participantContext.close()
  })
})
