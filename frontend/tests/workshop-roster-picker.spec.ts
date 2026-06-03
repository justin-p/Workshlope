// Covers instructor roster picker multi-select across pages
import {
  type APIRequestContext,
  expect,
  type Page,
  test,
} from "@playwright/test"

import { createUser } from "./utils/privateApi"

const apiBase = process.env.VITE_API_URL ?? "http://localhost:8000"

function waitForRosterPickerResponse(
  page: Page,
  sessionId: string,
  opts: { q: string; skip: number },
) {
  return page.waitForResponse((res) => {
    if (
      !res.url().includes(`/workshop/sessions/${sessionId}/roster-user-picker`)
    ) {
      return false
    }
    if (!res.ok()) return false
    const url = new URL(res.url())
    return (
      url.searchParams.get("q") === opts.q &&
      url.searchParams.get("skip") === String(opts.skip)
    )
  })
}

async function waitForRosterPickerEmail(
  request: APIRequestContext,
  sessionId: string,
  q: string,
  email: string,
  skip: number,
) {
  await expect
    .poll(
      async () => {
        const res = await request.get(
          `${apiBase}/api/v1/workshop/sessions/${sessionId}/roster-user-picker`,
          { params: { q, skip, limit: 25 } },
        )
        if (!res.ok()) return false
        const body = (await res.json()) as { data: Array<{ email: string }> }
        return body.data.some((row) => row.email === email)
      },
      { timeout: 60_000 },
    )
    .toBe(true)
}

test.describe("Workshop roster user picker", () => {
  test("multi-select persists across pages and adds trainees", async ({
    page,
    request,
  }) => {
    test.setTimeout(120_000)
    const prefix = `mselect_${Math.random().toString(36).slice(2, 8)}`
    const sessionRes = await request.post(
      `${apiBase}/api/v1/private/workshop/e2e-live-session/?omit_participant_seat=true`,
    )
    expect(sessionRes.ok()).toBeTruthy()
    const { session_id } = await sessionRes.json()
    await page.goto(`/workshop/${session_id}`)
    await expect(
      page.getByTestId("workshop-roster-user-picker-search"),
    ).toBeVisible()

    for (let i = 0; i < 30; i += 1) {
      const email = `${prefix}_${String(i).padStart(2, "0")}@example.com`
      await createUser({ email, password: "changethis123" })
    }

    const email0 = `${prefix}_00@example.com`
    const email25 = `${prefix}_25@example.com`
    await waitForRosterPickerEmail(request, session_id, prefix, email0, 0)
    await waitForRosterPickerEmail(request, session_id, prefix, email25, 25)
    const page1Ready = waitForRosterPickerResponse(page, session_id, {
      q: prefix,
      skip: 0,
    })
    await page.getByTestId("workshop-roster-user-picker-search").fill(prefix)
    await page1Ready
    const row0 = page.getByRole("checkbox", { name: `Select ${email0}` })
    await expect(row0).toBeVisible()
    await row0.click()
    const page2Ready = waitForRosterPickerResponse(page, session_id, {
      q: prefix,
      skip: 25,
    })
    await page.getByTestId("workshop-roster-user-picker-page-next").click()
    await page2Ready
    const row25 = page.getByRole("checkbox", { name: `Select ${email25}` })
    await expect(row25).toBeVisible()
    await row25.click()
    await page.getByTestId("workshop-roster-add-selected").click()
    const rosterList = page.getByTestId("workshop-roster-list")
    await expect(rosterList).toContainText(email0)
    await expect(rosterList).toContainText(email25)
  })

  test("picker table exposes column headers and remove clears roster", async ({
    page,
    request,
  }) => {
    const prefix = `rm_${Math.random().toString(36).slice(2, 8)}`
    const traineeEmail = `${prefix}@example.com`
    const sessionRes = await request.post(
      `${apiBase}/api/v1/private/workshop/e2e-live-session/?omit_participant_seat=true`,
    )
    expect(sessionRes.ok()).toBeTruthy()
    const { session_id } = await sessionRes.json()
    await createUser({ email: traineeEmail, password: "changethis123" })
    await page.goto(`/workshop/${session_id}`)
    await expect(page.getByTestId("workshop-roster-panel")).toBeVisible()

    const panel = page.getByTestId("workshop-roster-panel")
    await expect(
      panel.getByRole("columnheader", { name: "Type" }),
    ).toBeVisible()
    await expect(
      panel.getByRole("columnheader", { name: "Email" }),
    ).toBeVisible()
    await expect(
      panel.getByRole("columnheader", { name: "Full name" }),
    ).toBeVisible()

    const searchReady = waitForRosterPickerResponse(page, session_id, {
      q: prefix,
      skip: 0,
    })
    await page.getByTestId("workshop-roster-user-picker-search").fill(prefix)
    await searchReady
    const table = page.getByTestId("workshop-roster-user-picker-table")
    await expect(table).toContainText(traineeEmail)
    await page.getByRole("checkbox", { name: `Select ${traineeEmail}` }).click()
    await page.getByTestId("workshop-roster-add-selected").click()

    const rosterList = page.getByTestId("workshop-roster-list")
    await expect(rosterList).toContainText(traineeEmail)

    await page
      .getByRole("button", { name: `Remove ${traineeEmail} from roster` })
      .click()
    await expect(page.getByRole("dialog")).toBeVisible()
    await page.getByTestId("workshop-roster-remove-confirm").click()
    await expect(page.getByTestId("workshop-roster-empty")).toBeVisible()
  })

  test("search results show Instructor badge", async ({ page, request }) => {
    const prefix = `badge_${Math.random().toString(36).slice(2, 8)}`
    const instructorEmail = `${prefix}_i@example.com`
    const sessionRes = await request.post(
      `${apiBase}/api/v1/private/workshop/e2e-live-session/?omit_participant_seat=true`,
    )
    expect(sessionRes.ok()).toBeTruthy()
    const { session_id } = await sessionRes.json()
    await page.goto(`/workshop/${session_id}`)

    await createUser({
      email: instructorEmail,
      password: "changethis123",
      is_instructor: true,
    })

    const table = page.getByTestId("workshop-roster-user-picker-table")
    const searchReady = waitForRosterPickerResponse(page, session_id, {
      q: prefix,
      skip: 0,
    })
    await page.getByTestId("workshop-roster-user-picker-search").fill(prefix)
    await searchReady
    await expect(table).toContainText(instructorEmail)
    await expect(table).toContainText("Instructor")
  })
})
