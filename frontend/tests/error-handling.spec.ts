import { expect, test } from "@playwright/test"
import { MOCK_USER, mockBilling, mockEvents, mockUserMe } from "./utils/mocks"

test.describe("Error Handling", () => {
  test("404 for unknown route shows not-found", async ({ page }) => {
    await mockUserMe(page, MOCK_USER)
    await mockEvents(page)
    await mockBilling(page)
    await page.route("**/api/v1/repositories**", (route) => {
      route.fulfill({ json: [] })
    })
    await page.route("**/api/v1/workflow/scans**", (route) => {
      route.fulfill({ json: [] })
    })
    await page.route("**/api/v1/workflow/findings**", (route) => {
      route.fulfill({ json: [] })
    })
    await page.route("**/api/v1/rules**", (route) => {
      route.fulfill({ json: [] })
    })

    await page.goto("/nonexistent-page-12345")

    await expect(page.getByTestId("not-found")).toBeVisible()
  })

  test("analysis not found shows alert", async ({ page }) => {
    await mockUserMe(page, MOCK_USER)
    await mockEvents(page)
    await mockBilling(page)
    await page.route("**/api/v1/repositories**", (route) => {
      route.fulfill({ json: [] })
    })
    await page.route("**/api/v1/rules**", (route) => {
      route.fulfill({ json: [] })
    })
    await page.route("**/api/v1/workflow/scans**", (route) => {
      route.fulfill({ status: 404, json: { detail: "Not found" } })
    })
    await page.route("**/api/v1/workflow/findings**", (route) => {
      route.fulfill({ json: [] })
    })
    await page.route("**/api/v1/workflow/fixes**", (route) => {
      route.fulfill({ json: [] })
    })

    await page.goto("/analyses/00000000-0000-0000-0000-999999999999")

    await expect(
      page.getByText("Analysis not found or failed to load."),
    ).toBeVisible({ timeout: 15000 })
  })

  test("token invalidation redirects to login", async ({ page }) => {
    await mockUserMe(page, MOCK_USER)
    await mockEvents(page)
    await mockBilling(page)
    await page.route("**/api/v1/repositories**", (route) => {
      route.fulfill({ json: [] })
    })
    await page.route("**/api/v1/workflow/scans**", (route) => {
      route.fulfill({ json: [] })
    })
    await page.route("**/api/v1/workflow/findings**", (route) => {
      route.fulfill({ json: [] })
    })
    await page.route("**/api/v1/rules**", (route) => {
      route.fulfill({ json: [] })
    })

    await page.goto("/dashboard")
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible()

    await page.evaluate(() => localStorage.removeItem("access_token"))

    await page.route("**/api/v1/users/me", (route) => {
      route.fulfill({ status: 401, json: { detail: "Not authenticated" } })
    })

    await page.goto("/dashboard")

    await expect(page).toHaveURL(/\/login/, { timeout: 10000 })
  })

  test("API 500 shows error state on repo static analysis page", async ({
    page,
  }) => {
    await mockUserMe(page, MOCK_USER)
    await mockEvents(page)
    await mockBilling(page)
    const repoId = "00000000-0000-0000-0000-000000000001"
    await page.route("**/api/v1/repositories**", (route) => {
      const url = route.request().url()
      if (url.match(/\/repositories\/[0-9a-f-]{36}$/)) {
        route.fulfill({
          json: {
            id: repoId,
            full_name: "acme/web-app",
            enabled: true,
            is_external: false,
            default_branch: "main",
            tier: "free",
            created_at: "2024-01-01T00:00:00Z",
            avg_score: null,
            grade: null,
          },
        })
      } else {
        route.fulfill({ json: [] })
      }
    })
    await page.route("**/api/v1/workflow/scans**", (route) => {
      route.fulfill({ json: [] })
    })
    await page.route("**/api/v1/rules**", (route) => {
      route.fulfill({ json: [] })
    })
    await page.route("**/api/v1/workflow/findings**", (route) => {
      route.fulfill({ status: 500, json: { detail: "Internal error" } })
    })
    await page.route("**/api/v1/workflow/fixes**", (route) => {
      route.fulfill({ json: [] })
    })

    await page.goto(`/repositories/${repoId}/static-analysis`)

    await expect(page.getByText("No workflow files found")).toBeVisible({
      timeout: 15000,
    })
  })
})
