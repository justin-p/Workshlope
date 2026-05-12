// Covers instructor roster picker multi-select across pages
import { expect, test } from "@playwright/test"

import { createUser } from "./utils/privateApi"

const apiBase = process.env.VITE_API_URL ?? "http://localhost:8000"

test.describe("Workshop roster user picker", () => {
  test("multi-select persists across pages and adds trainees", async ({
    page,
    request,
  }) => {
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

    await Promise.all(
      Array.from({ length: 30 }, (_, i) => {
        const email = `${prefix}_${String(i).padStart(2, "0")}@example.com`
        return createUser({ email, password: "changethis123" })
      }),
    )

    const email0 = `${prefix}_00@example.com`
    const email25 = `${prefix}_25@example.com`
    await page.getByTestId("workshop-roster-user-picker-search").fill(prefix)
    await page.waitForLoadState("networkidle")
    const row0 = page.getByRole("checkbox", { name: `Select ${email0}` })
    await expect(row0).toBeVisible({ timeout: 15_000 })
    await row0.click()
    await page.getByTestId("workshop-roster-user-picker-page-next").click()
    await page.waitForLoadState("networkidle")
    const row25 = page.getByRole("checkbox", { name: `Select ${email25}` })
    await expect(row25).toBeVisible({ timeout: 15_000 })
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
    await page.waitForLoadState("networkidle")

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

    await page.getByTestId("workshop-roster-user-picker-search").fill(prefix)
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
    await page.getByTestId("workshop-roster-user-picker-search").fill(prefix)
    await expect(table).toContainText(instructorEmail)
    await expect(table).toContainText("Instructor")
  })
})
