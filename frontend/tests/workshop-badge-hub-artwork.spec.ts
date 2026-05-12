// Hub uploads badge artwork; row points at anonymous image URL; browser decodes bytes (naturalWidth > 0).
import { expect, test } from "@playwright/test"
import { getApiTokenAsSuperuser } from "./utils/bridgeToken"

const apiBase = process.env.VITE_API_URL ?? "http://localhost:8000"

/** 1×1 RGBA PNG decodable by Chromium (classic transparent pixel). */
const MINIMAL_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
)

test.describe("Workshop badge hub artwork", () => {
  test("upload sets API image URL and thumbnail decodes", async ({
    page,
    request,
  }) => {
    const slug = `e2e-art-${Date.now()}`
    await page.goto("/workshop/badges/new")
    await page.waitForLoadState("networkidle")
    await page.getByTestId("workshop-badge-wizard-slug").fill(slug)
    await page
      .getByTestId("workshop-badge-wizard-title")
      .fill("E2E artwork hub")
    await page.getByTestId("workshop-badge-wizard-points").fill("3")
    await page.getByTestId("workshop-badge-wizard-submit").click()
    await page.waitForURL("**/workshop/badges", { timeout: 15_000 })
    await expect(page.getByTestId(`workshop-badge-row-${slug}`)).toBeVisible({
      timeout: 10_000,
    })

    const token = await getApiTokenAsSuperuser()
    const list = await request.get(`${apiBase}/api/v1/workshop/badges`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(list.ok()).toBeTruthy()
    const badges = (await list.json()) as {
      data: Array<{ id: string; slug: string }>
    }
    const badge = badges.data.find((b) => b.slug === slug)
    expect(badge).toBeTruthy()
    const badgeId = badge!.id

    await page.getByTestId(`workshop-badge-hub-artwork-open-${slug}`).click()
    await expect(
      page.getByTestId("workshop-badge-hub-artwork-dialog"),
    ).toBeVisible({ timeout: 10_000 })
    await page.getByTestId("workshop-badge-hub-artwork-file").setInputFiles({
      name: "t.png",
      mimeType: "image/png",
      buffer: MINIMAL_PNG,
    })
    await page.getByTestId("workshop-badge-hub-artwork-upload").click()
    await expect(
      page.getByTestId("workshop-badge-hub-artwork-dialog"),
    ).toBeHidden({ timeout: 15_000 })

    const thumb = page.getByTestId(`workshop-badge-img-${badgeId}`)
    await expect(thumb).toBeVisible()
    await expect(thumb).toHaveAttribute(
      "src",
      new RegExp(`/api/v1/workshop/badges/${badgeId}/image`),
    )
    await expect
      .poll(
        async () => thumb.evaluate((el: HTMLImageElement) => el.naturalWidth),
        { timeout: 15_000 },
      )
      .toBeGreaterThan(0)
  })
})
