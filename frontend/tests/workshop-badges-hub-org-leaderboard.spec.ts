// Badge hub wizard, org-wide grant via API, global leaderboard visibility for trainee and instructor.
import { expect, test } from "@playwright/test"
import { getApiTokenAsSuperuser } from "./utils/bridgeToken"
import { createUser } from "./utils/privateApi"
import { randomEmail } from "./utils/random"

const apiBase = process.env.VITE_API_URL ?? "http://localhost:8000"

test.describe("Badge hub, org grant, global leaderboard", () => {
  test.describe.configure({ mode: "serial" })

  test("wizard creates badge; org grant appears on global leaderboard for trainee", async ({
    page,
    request,
  }) => {
    const traineeEmail = randomEmail()
    const traineePassword = "changethis123"
    const trainee = await createUser({
      email: traineeEmail,
      password: traineePassword,
    })

    const slug = `e2e-org-${Date.now()}`
    await page.goto("/workshop/badges/new")
    await page.waitForLoadState("networkidle")
    await page.getByTestId("workshop-badge-wizard-slug").fill(slug)
    await page.getByTestId("workshop-badge-wizard-title").fill("E2E org badge")
    await page.getByTestId("workshop-badge-wizard-points").fill("9")
    await page.getByTestId("workshop-badge-wizard-submit").click()
    await page.waitForURL("**/workshop/badges", { timeout: 15_000 })
    await expect(page.getByTestId(`workshop-badge-row-${slug}`)).toBeVisible({
      timeout: 10_000,
    })

    const token = await getApiTokenAsSuperuser()
    const auth = { Authorization: `Bearer ${token}` }
    const list = await request.get(`${apiBase}/api/v1/workshop/badges`, {
      headers: auth,
    })
    expect(list.ok()).toBeTruthy()
    const badges = (await list.json()) as {
      data: Array<{ id: string; slug: string }>
    }
    const badge = badges.data.find((b) => b.slug === slug)
    expect(badge).toBeTruthy()

    // Playwright APIRequestContext uses `data` for JSON bodies — `json` is ignored (empty body → 422).
    const grantRes = await request.post(
      `${apiBase}/api/v1/workshop/badges/org/grant`,
      { headers: auth, data: { user_id: trainee.id, badge_id: badge!.id } },
    )
    expect(
      grantRes.ok(),
      `org grant failed: ${grantRes.status()} ${await grantRes.text()}`,
    ).toBeTruthy()

    await page.goto("/workshop/badges/leaderboard")
    await page.waitForLoadState("networkidle")
    await expect(
      page.getByTestId(`workshop-global-lb-row-${trainee.id}`),
    ).toBeVisible({ timeout: 10_000 })
    await expect(
      page.getByTestId(`workshop-global-lb-points-${trainee.id}`),
    ).toHaveText("9")
  })
})
