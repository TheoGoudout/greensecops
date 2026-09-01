import { expect, test } from "@playwright/test"
import {
  MOCK_REPO,
  MOCK_REPO_DISABLED,
  MOCK_REPO_PRIVATE,
  mockAnalyses,
  mockBilling,
  mockEvents,
  mockIssues,
  mockRepositories,
  mockRules,
  mockUserMe,
} from "./utils/mocks"

test.describe("Workflows", () => {
  test.beforeEach(async ({ page }) => {
    await mockUserMe(page)
    await mockEvents(page)
    await mockBilling(page)
    await mockRules(page)
    await mockIssues(page, [])
    await mockAnalyses(page, [])
  })

  test("shows repo list with name, branch, and grade", async ({ page }) => {
    await mockRepositories(page, [MOCK_REPO, MOCK_REPO_DISABLED])

    await page.goto("/workflows")

    await expect(page.getByRole("heading", { name: "Workflows" })).toBeVisible()
    await expect(page.getByText("acme/web-app")).toBeVisible()
    await expect(page.getByText("acme/old-service")).toBeVisible()
    await expect(page.getByText("main").first()).toBeVisible()
  })

  test("shows lock icon for private repos only", async ({ page }) => {
    await mockRepositories(page, [MOCK_REPO, MOCK_REPO_PRIVATE])

    await page.goto("/workflows")

    const publicRow = page.getByText("acme/web-app").locator("..")
    const privateRow = page.getByText("acme/secret-service").locator("..")
    await expect(
      privateRow.locator('[aria-label="Private repository"]'),
    ).toBeVisible()
    await expect(
      publicRow.locator('[aria-label="Private repository"]'),
    ).toHaveCount(0)
  })

  test("empty state when no repos", async ({ page }) => {
    await mockRepositories(page, [])

    await page.goto("/workflows")

    await expect(
      page.getByText(
        "No repositories found. Install the GitHub App to get started.",
      ),
    ).toBeVisible()
  })

  test("enable/disable toggle calls API", async ({ page }) => {
    let toggleCalled = false
    await page.route("**/api/v1/repositories**", (route) => {
      const url = route.request().url()
      const method = route.request().method()
      if (method === "PATCH") {
        toggleCalled = true
        route.fulfill({
          json: { ...MOCK_REPO, enabled: false },
        })
      } else if (url.match(/\/repositories\/[0-9a-f-]{36}$/)) {
        route.fulfill({ json: MOCK_REPO })
      } else {
        route.fulfill({ json: [MOCK_REPO] })
      }
    })

    await page.goto("/workflows")

    const switchEl = page.locator("button[role='switch']").first()
    await switchEl.click()

    expect(toggleCalled).toBe(true)
  })

  test("trigger analysis button calls API and shows toast", async ({
    page,
  }) => {
    await mockRepositories(page, [MOCK_REPO])

    let triggerCalled = false
    await page.route(
      /\/api\/v1\/workflow\/(repositories\/[^/]+\/)?scans/,
      (route) => {
        const method = route.request().method()
        if (method === "POST") {
          triggerCalled = true
          route.fulfill({
            status: 202,
            json: { status: "queued", repo_id: MOCK_REPO.id },
          })
        } else {
          route.fulfill({ json: [] })
        }
      },
    )

    await page.goto("/workflows")

    await page.getByRole("button", { name: "Trigger analysis" }).click()

    expect(triggerCalled).toBe(true)
    await expect(page.getByText("Analysis queued")).toBeVisible()
  })

  test("clicking repo navigates to detail", async ({ page }) => {
    await mockRepositories(page, [MOCK_REPO])

    await page.goto("/workflows")

    await page.getByText("acme/web-app").click()

    await expect(page).toHaveURL(new RegExp(`/workflows/${MOCK_REPO.id}`))
  })

  test("Install GitHub App button is visible", async ({ page }) => {
    await mockRepositories(page, [MOCK_REPO])

    await page.goto("/workflows")

    await expect(
      page.getByRole("button", { name: "Install GitHub App" }),
    ).toBeVisible()
  })

  test("loading skeletons appear while data loads", async ({ page }) => {
    await page.route("**/api/v1/repositories**", async (route) => {
      await new Promise((r) => setTimeout(r, 2000))
      route.fulfill({ json: [] })
    })

    await page.goto("/workflows")

    await expect(page.locator(".animate-pulse").first()).toBeVisible()
  })
})
