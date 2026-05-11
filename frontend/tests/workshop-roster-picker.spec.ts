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

    const table = page.getByTestId("workshop-roster-user-picker-table")
    const email0 = `${prefix}_00@example.com`
    const email25 = `${prefix}_25@example.com`
    await page.getByTestId("workshop-roster-user-picker-search").fill(prefix)
    await expect(table).toContainText(email0)
    await page.getByRole("checkbox", { name: `Select ${email0}` }).click()
    await page.getByTestId("workshop-roster-user-picker-page-next").click()
    await expect(table).toContainText(email25)
    await page.getByRole("checkbox", { name: `Select ${email25}` }).click()
    await page.getByTestId("workshop-roster-add-selected").click()
    const rosterList = page.getByTestId("workshop-roster-list")
    await expect(rosterList).toContainText(email0)
    await expect(rosterList).toContainText(email25)
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
