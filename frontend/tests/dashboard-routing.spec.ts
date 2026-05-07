import { expect, test } from "@playwright/test"
import { firstSuperuser, firstSuperuserPassword } from "./config.ts"
import { createUser } from "./utils/privateApi"
import { randomEmail } from "./utils/random"

test.use({ storageState: { cookies: [], origins: [] } })

test("superuser without instructor flag lands on admin home after login", async ({
  page,
}) => {
  await page.goto("/login")
  await page.getByTestId("email-input").fill(firstSuperuser)
  await page.getByTestId("password-input").fill(firstSuperuserPassword)
  await page.getByRole("button", { name: "Log In" }).click()
  await page.waitForURL("/dashboard/admin")
  await expect(
    page.getByRole("heading", { level: 1, name: "Admin Home" }),
  ).toBeVisible()
  await expect(page.getByTestId("dashboard-stub-rail-admin")).toBeVisible()
  await expect(page.getByTestId("dashboard-workshop-sessions")).toBeVisible()
})

test("root path redirects superuser to role dashboard", async ({ page }) => {
  await page.goto("/login")
  await page.getByTestId("email-input").fill(firstSuperuser)
  await page.getByTestId("password-input").fill(firstSuperuserPassword)
  await page.getByRole("button", { name: "Log In" }).click()
  await page.waitForURL("/dashboard/admin")
  await page.goto("/")
  await page.waitForURL("/dashboard/admin")
})

test("instructor dashboard redirects non-instructor superuser to their home", async ({
  page,
}) => {
  await page.goto("/login")
  await page.getByTestId("email-input").fill(firstSuperuser)
  await page.getByTestId("password-input").fill(firstSuperuserPassword)
  await page.getByRole("button", { name: "Log In" }).click()
  await page.waitForURL("/dashboard/admin")
  await page.goto("/dashboard/instructor")
  await page.waitForURL("/dashboard/admin")
})

test("login tolerates stale access token without redirect loop", async ({
  page,
}) => {
  await page.addInitScript(() => {
    localStorage.setItem("access_token", "stale-token")
  })

  await page.goto("/login")
  await page.waitForURL("/login")
  await expect(
    page.getByRole("heading", { name: "Login to your account" }),
  ).toBeVisible()
  await expect
    .poll(async () =>
      page.evaluate(() => window.localStorage.getItem("access_token")),
    )
    .toBeNull()
})

test("trainee dashboard shows settings rail shortcut", async ({ browser }) => {
  const email = randomEmail()
  const password = "changethis123"
  await createUser({ email, password })

  const context = await browser.newContext({
    storageState: { cookies: [], origins: [] },
  })
  const page = await context.newPage()
  await page.goto("/login")
  await page.getByTestId("email-input").fill(email)
  await page.getByTestId("password-input").fill(password)
  await page.getByRole("button", { name: "Log In" }).click()
  await page.waitForURL("/dashboard/trainee")

  await expect(page.getByTestId("dashboard-stub-rail-trainee")).toBeVisible()
  await page.getByRole("link", { name: "Open settings" }).click()
  await page.waitForURL("/settings")
  await context.close()
})

test("admin dashboard shows admin rail shortcut", async ({ page }) => {
  await page.goto("/login")
  await page.getByTestId("email-input").fill(firstSuperuser)
  await page.getByTestId("password-input").fill(firstSuperuserPassword)
  await page.getByRole("button", { name: "Log In" }).click()
  await page.waitForURL("/dashboard/admin")

  await expect(page.getByTestId("dashboard-stub-rail-admin")).toBeVisible()
  await page.getByRole("link", { name: "Open admin" }).click()
  await page.waitForURL("/admin")
})

test("admin can access workshops hub route", async ({ page }) => {
  await page.goto("/login")
  await page.getByTestId("email-input").fill(firstSuperuser)
  await page.getByTestId("password-input").fill(firstSuperuserPassword)
  await page.getByRole("button", { name: "Log In" }).click()
  await page.waitForURL("/dashboard/admin")

  await page.goto("/workshops")
  await page.waitForURL("/workshops")
  await expect(
    page.getByRole("heading", { level: 1, name: "Workshops hub" }),
  ).toBeVisible()
})

test("trainee dashboard shows expected stub rail cards", async ({
  browser,
}) => {
  const email = randomEmail()
  const password = "changethis123"
  await createUser({ email, password })

  const context = await browser.newContext({
    storageState: { cookies: [], origins: [] },
  })
  const page = await context.newPage()
  await page.goto("/login")
  await page.getByTestId("email-input").fill(email)
  await page.getByTestId("password-input").fill(password)
  await page.getByRole("button", { name: "Log In" }).click()
  await page.waitForURL("/dashboard/trainee")

  const rail = page.getByTestId("dashboard-stub-rail-trainee")
  await expect(rail).toContainText("Continue learning")
  await expect(rail).toContainText("Badges & progress")
  await expect(rail).toContainText("Account")
  await context.close()
})

test("instructor can access workshops sync card", async ({ browser }) => {
  const email = randomEmail()
  const password = "changethis123"
  await createUser({ email, password, is_instructor: true })

  const context = await browser.newContext({
    storageState: { cookies: [], origins: [] },
  })
  const page = await context.newPage()
  await page.goto("/login")
  await page.getByTestId("email-input").fill(email)
  await page.getByTestId("password-input").fill(password)
  await page.getByRole("button", { name: "Log In" }).click()
  await page.waitForURL("/dashboard/instructor")

  await page.goto("/workshops")
  await page.waitForURL("/workshops")
  await expect(page.getByTestId("workshop-lesson-repo-sync-card")).toBeVisible()
  await context.close()
})

test("instructor sync card shows installation settings link and repo parts preview", async ({
  browser,
}) => {
  const email = randomEmail()
  const password = "changethis123"
  await createUser({ email, password, is_instructor: true })

  const context = await browser.newContext({
    storageState: { cookies: [], origins: [] },
  })
  const page = await context.newPage()

  await page.route("**/api/v1/workshop/lesson-repos/installations**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        data: [
          {
            installation_id: 123456,
            account_login: "acme-org",
            account_type: "Organization",
            repository_selection: "selected",
            app_slug: "lesson-bot",
            suspended: false,
            entitled_repositories_count: 1,
            entitled_repositories: ["acme-org/workshop-lessons"],
            installation_settings_url:
              "https://github.com/settings/installations/123456",
          },
        ],
        count: 1,
      }),
    }),
  )
  await page.route("**/api/v1/workshop/lesson-repos?**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        data: [
          {
            lesson_repo_id: "11111111-1111-4111-8111-111111111111",
            full_name: "acme-org/workshop-lessons",
            default_branch: "main",
            health: "healthy",
            github_installation_id: 123456,
            last_synced_at: "2026-05-07T10:00:00Z",
            lesson_count: 1,
            part_count: 2,
            manifest_count: 1,
            last_manifest_synced_at: "2026-05-07T10:02:00Z",
          },
        ],
        count: 1,
      }),
    }),
  )
  await page.route(
    "**/api/v1/workshop/lesson-repos/11111111-1111-4111-8111-111111111111/preview",
    (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          lesson_repo_id: "11111111-1111-4111-8111-111111111111",
          full_name: "acme-org/workshop-lessons",
          default_branch: "main",
          health: "healthy",
          lessons: [
            {
              lesson_id: "22222222-2222-4222-8222-222222222222",
              lesson_slug: "intro",
              lesson_title: "Intro Lesson",
              parts: [
                {
                  slug: "welcome",
                  title: "Welcome",
                  ordering: 0,
                  path: "welcome.md",
                },
                {
                  slug: "setup",
                  title: "Setup",
                  ordering: 1,
                  path: "setup.md",
                },
              ],
            },
          ],
        }),
      }),
  )

  await page.goto("/login")
  await page.getByTestId("email-input").fill(email)
  await page.getByTestId("password-input").fill(password)
  await page.getByRole("button", { name: "Log In" }).click()
  await page.waitForURL("/dashboard/instructor")

  await page.goto("/workshops")
  await page.waitForURL("/workshops")
  await expect(page.getByTestId("workshop-lesson-repo-sync-card")).toBeVisible()
  await expect(
    page.getByRole("link", { name: "Open settings" }),
  ).toHaveAttribute("href", "https://github.com/settings/installations/123456")

  await page.getByTestId("workshop-repo-preview-toggle").click()
  await expect(page.getByTestId("workshop-repo-preview-panel")).toContainText(
    "Parts preview for",
  )
  await expect(page.getByTestId("workshop-repo-preview-panel")).toContainText(
    "Intro Lesson",
  )
  await expect(page.getByTestId("workshop-repo-preview-panel")).toContainText(
    "1. Welcome | 2. Setup",
  )

  await context.close()
})

test("instructor sync card install CTA prefers app install URL from API", async ({
  browser,
}) => {
  const email = randomEmail()
  const password = "changethis123"
  await createUser({ email, password, is_instructor: true })

  const context = await browser.newContext({
    storageState: { cookies: [], origins: [] },
  })
  const page = await context.newPage()

  await page.route("**/api/v1/workshop/lesson-repos/installations**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        data: [],
        count: 0,
        install_url: "https://github.com/apps/lesson-bot/installations/new",
      }),
    }),
  )
  await page.route("**/api/v1/workshop/lesson-repos?**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        data: [],
        count: 0,
      }),
    }),
  )

  await page.goto("/login")
  await page.getByTestId("email-input").fill(email)
  await page.getByTestId("password-input").fill(password)
  await page.getByRole("button", { name: "Log In" }).click()
  await page.waitForURL("/dashboard/instructor")

  await page.goto("/workshops")
  await page.waitForURL("/workshops")
  await expect(page.getByTestId("workshop-lesson-repo-sync-card")).toBeVisible()
  await expect(
    page.getByRole("link", { name: "GitHub App installations" }),
  ).toHaveAttribute(
    "href",
    "https://github.com/apps/lesson-bot/installations/new",
  )

  await context.close()
})

test("instructor sync card prompts install and blocks sync when no installations", async ({
  browser,
}) => {
  const email = randomEmail()
  const password = "changethis123"
  await createUser({ email, password, is_instructor: true })

  const context = await browser.newContext({
    storageState: { cookies: [], origins: [] },
  })
  const page = await context.newPage()

  await page.route("**/api/v1/workshop/lesson-repos/installations**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        data: [],
        count: 0,
        install_url: "https://github.com/apps/lesson-bot/installations/new",
      }),
    }),
  )
  await page.route("**/api/v1/workshop/lesson-repos?**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        data: [],
        count: 0,
      }),
    }),
  )

  await page.goto("/login")
  await page.getByTestId("email-input").fill(email)
  await page.getByTestId("password-input").fill(password)
  await page.getByRole("button", { name: "Log In" }).click()
  await page.waitForURL("/dashboard/instructor")

  await page.goto("/workshops")
  await page.waitForURL("/workshops")
  await expect(page.getByTestId("workshop-sync-install-prompt")).toBeVisible()
  await expect(
    page.getByRole("link", { name: "Install GitHub App" }),
  ).toHaveAttribute(
    "href",
    "https://github.com/apps/lesson-bot/installations/new",
  )

  await page
    .getByTestId("workshop-sync-full-name")
    .fill("acme/workshop-lessons")
  await page.getByTestId("workshop-sync-installation-id").fill("123456")
  await expect(page.getByTestId("workshop-sync-submit")).toBeDisabled()

  await context.close()
})

test("selected installation without entitled repos prompts grant access and blocks sync", async ({
  browser,
}) => {
  const email = randomEmail()
  const password = "changethis123"
  await createUser({ email, password, is_instructor: true })

  const context = await browser.newContext({
    storageState: { cookies: [], origins: [] },
  })
  const page = await context.newPage()

  await page.route("**/api/v1/workshop/lesson-repos/installations**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        data: [
          {
            installation_id: 123456,
            account_login: "acme-org",
            account_type: "Organization",
            repository_selection: "selected",
            app_slug: "lesson-bot",
            suspended: false,
            entitled_repositories_count: 0,
            entitled_repositories: [],
            installation_settings_url:
              "https://github.com/settings/installations/123456",
          },
        ],
        count: 1,
      }),
    }),
  )
  await page.route("**/api/v1/workshop/lesson-repos?**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        data: [],
        count: 0,
      }),
    }),
  )

  await page.goto("/login")
  await page.getByTestId("email-input").fill(email)
  await page.getByTestId("password-input").fill(password)
  await page.getByRole("button", { name: "Log In" }).click()
  await page.waitForURL("/dashboard/instructor")

  await page.goto("/workshops")
  await page.waitForURL("/workshops")
  await page.getByTestId("workshop-sync-installation-id").fill("123456")
  await page
    .getByTestId("workshop-sync-full-name")
    .fill("acme/workshop-lessons")
  await expect(
    page.getByTestId("workshop-sync-grant-access-prompt"),
  ).toBeVisible()
  await expect(
    page.getByRole("link", { name: "Grant repository access" }),
  ).toHaveAttribute("href", "https://github.com/settings/installations/123456")
  await expect(page.getByTestId("workshop-sync-submit")).toBeDisabled()

  await context.close()
})

test("instructor sync card passes health and query filters to repo API", async ({
  browser,
}) => {
  const email = randomEmail()
  const password = "changethis123"
  await createUser({ email, password, is_instructor: true })

  const context = await browser.newContext({
    storageState: { cookies: [], origins: [] },
  })
  const page = await context.newPage()
  const seenHealth: string[] = []
  const seenQuery: Array<string | null> = []

  await page.route("**/api/v1/workshop/lesson-repos/installations**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        data: [],
        count: 0,
      }),
    }),
  )
  await page.route("**/api/v1/workshop/lesson-repos?**", (route) => {
    const requestUrl = new URL(route.request().url())
    const health = requestUrl.searchParams.get("health") ?? "all"
    seenHealth.push(health)
    seenQuery.push(requestUrl.searchParams.get("q"))
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        data: [],
        count: 0,
      }),
    })
  })

  await page.goto("/login")
  await page.getByTestId("email-input").fill(email)
  await page.getByTestId("password-input").fill(password)
  await page.getByRole("button", { name: "Log In" }).click()
  await page.waitForURL("/dashboard/instructor")

  await page.goto("/workshops")
  await page.waitForURL("/workshops")
  await expect(page.getByTestId("workshop-lesson-repo-sync-card")).toBeVisible()

  await expect.poll(() => seenHealth.length).toBeGreaterThan(0)
  await expect.poll(() => seenHealth.includes("all")).toBeTruthy()

  await page.getByTestId("workshop-sync-unhealthy-toggle").click()
  await expect.poll(() => seenHealth.includes("unhealthy")).toBeTruthy()

  await page.getByTestId("workshop-sync-unhealthy-toggle").click()
  await expect.poll(() => seenHealth.includes("healthy")).toBeTruthy()

  await page.getByTestId("workshop-sync-repo-search").fill("acme-org")
  await expect
    .poll(() => seenQuery.filter((value) => value === "acme-org").length)
    .toBeGreaterThan(0)

  await context.close()
})
