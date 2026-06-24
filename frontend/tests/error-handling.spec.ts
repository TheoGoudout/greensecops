import { expect, test } from "@playwright/test"
import {
  MOCK_ANALYSIS,
  MOCK_USER,
  mockBilling,
  mockEvents,
  mockUserMe,
} from "./utils/mocks"

test.describe("Error Handling", () => {
  test("404 for unknown route shows not-found", async ({ page }) => {
    await mockUserMe(page, MOCK_USER)
    await mockEvents(page)
    await mockBilling(page)
    await page.route("**/api/v1/repositories/**", (route) => {
      route.fulfill({ json: [] })
    })
    await page.route("**/api/v1/analyses/**", (route) => {
      route.fulfill({ json: [] })
    })
    await page.route("**/api/v1/issues/**", (route) => {
      route.fulfill({ json: [] })
    })
    await page.route("**/api/v1/rules/**", (route) => {
      route.fulfill({ json: [] })
    })

    await page.goto("/nonexistent-page-12345")

    await expect(page.getByTestId("not-found")).toBeVisible()
  })

  test("analysis not found shows alert", async ({ page }) => {
    await mockUserMe(page, MOCK_USER)
    await mockEvents(page)
    await mockBilling(page)
    await page.route("**/api/v1/repositories/**", (route) => {
      route.fulfill({ json: [] })
    })
    await page.route("**/api/v1/rules/**", (route) => {
      route.fulfill({ json: [] })
    })
    await page.route("**/api/v1/analyses/**", (route) => {
      route.fulfill({ status: 404, json: { detail: "Not found" } })
    })
    await page.route("**/api/v1/issues/**", (route) => {
      route.fulfill({ json: [] })
    })
    await page.route("**/api/v1/fixes/**", (route) => {
      route.fulfill({ json: [] })
    })

    await page.goto("/analyses/00000000-0000-0000-0000-999999999999")

    await expect(
      page.getByText("Analysis not found or failed to load."),
    ).toBeVisible()
  })

  test("token invalidation redirects to login", async ({ page }) => {
    await mockUserMe(page, MOCK_USER)
    await mockEvents(page)
    await mockBilling(page)
    await page.route("**/api/v1/repositories/**", (route) => {
      route.fulfill({ json: [] })
    })
    await page.route("**/api/v1/analyses/**", (route) => {
      route.fulfill({ json: [] })
    })
    await page.route("**/api/v1/issues/**", (route) => {
      route.fulfill({ json: [] })
    })
    await page.route("**/api/v1/rules/**", (route) => {
      route.fulfill({ json: [] })
    })

    await page.goto("/dashboard")
    await expect(page.getByText("Dashboard")).toBeVisible()

    await page.evaluate(() => localStorage.removeItem("access_token"))

    await page.route("**/api/v1/users/me", (route) => {
      route.fulfill({ status: 401, json: { detail: "Not authenticated" } })
    })

    await page.goto("/dashboard")

    await expect(page).toHaveURL(/\/login/, { timeout: 10000 })
  })

  test("API 500 shows error state on issues page", async ({ page }) => {
    await mockUserMe(page, MOCK_USER)
    await mockEvents(page)
    await mockBilling(page)
    await page.route("**/api/v1/repositories/**", (route) => {
      route.fulfill({ json: [] })
    })
    await page.route("**/api/v1/analyses/**", (route) => {
      route.fulfill({ json: [] })
    })
    await page.route("**/api/v1/rules/**", (route) => {
      route.fulfill({ json: [] })
    })
    await page.route("**/api/v1/issues/**", (route) => {
      route.fulfill({ status: 500, json: { detail: "Internal error" } })
    })

    await page.goto("/issues")

    await expect(page.getByText("Failed to load issues.")).toBeVisible()
  })
})
