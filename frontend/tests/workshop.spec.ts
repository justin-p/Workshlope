import { expect, test } from "@playwright/test"

const apiBase = process.env.VITE_API_URL ?? "http://localhost:8000"

test.describe("Workshop live session", () => {
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
    await expect(page.getByTestId("workshop-ws-last-raw")).toContainText(
      "live_status.ack",
    )
  })
})
