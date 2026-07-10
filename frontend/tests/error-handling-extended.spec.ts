import { expect, test } from "@playwright/test"
import {
  MOCK_REPO,
  MOCK_USER,
  mockBilling,
  mockEvents,
  mockRules,
  mockUserMe,
} from "./utils/mocks"

test.describe("Error Handling — Extended", () => {
  test.beforeEach(async ({ page }) => {
    await mockUserMe(page, MOCK_USER)
    await mockEvents(page)
    await mockBilling(page)
    await mockRules(page)
    await page.route("**/api/v1/repositories/**", (route) => {
      route.fulfill({ json: [] })
    })
    await page.route("**/api/v1/analyses/**", (route) => {
      route.fulfill({ json: [] })
    })
    await page.route("**/api/v1/issues/**", (route) => {
      route.fulfill({ json: [] })
    })
  })

  test("fix detail 404 shows error state", async ({ page }) => {
    await page.route("**/api/v1/fixes/**", (route) => {
      route.fulfill({ status: 404, json: { detail: "Fix not found" } })
    })

    await page.goto("/fixes/00000000-0000-0000-0000-999999999999")

    await expect(
      page.getByText(/not found|failed to load|fix not found/i),
    ).toBeVisible({ timeout: 15000 })
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("repository detail 404 does not crash the app", async ({ page }) => {
    await page.route("**/api/v1/repositories/**", (route) => {
      route.fulfill({ status: 404, json: { detail: "Repository not found" } })
    })

    await page.goto("/repositories/00000000-0000-0000-0000-999999999999")

    await page.waitForLoadState("networkidle")
    await expect(page.locator("body")).not.toContainText("Something went wrong")
    await expect(page.locator("body")).not.toContainText("Unhandled")
  })

  test("SSE endpoint returning 500 does not crash the app", async ({
    page,
  }) => {
    await page.route("**/api/v1/events/**", (route) => {
      route.fulfill({
        status: 500,
        headers: { "Content-Type": "text/event-stream" },
        body: "",
      })
    })

    await page.route("**/api/v1/repositories/**", (route) => {
      route.fulfill({ json: [MOCK_REPO] })
    })

    await page.goto("/dashboard")

    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible()
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("fix list API 500 shows empty or error state without crashing", async ({
    page,
  }) => {
    await page.route("**/api/v1/repositories/**", (route) => {
      const url = route.request().url()
      if (url.includes("/branches")) {
        route.fulfill({ json: ["main"] })
      } else if (url.match(/\/repositories\/[0-9a-f-]{36}$/)) {
        route.fulfill({ json: MOCK_REPO })
      } else {
        route.fulfill({ json: [MOCK_REPO] })
      }
    })
    await page.route("**/api/v1/fixes/**", (route) => {
      route.fulfill({ status: 500, json: { detail: "Internal error" } })
    })

    await page.goto(`/repositories/${MOCK_REPO.id}/fixes`)

    await expect(page.getByText(/no fixes|error|failed/i).first()).toBeVisible({
      timeout: 15000,
    })
    await expect(page.locator("body")).not.toContainText("Unhandled")
  })

  test("analyses API 500 shows empty state not crash", async ({ page }) => {
    await page.route("**/api/v1/repositories/**", (route) => {
      const url = route.request().url()
      if (url.includes("/branches")) {
        route.fulfill({ json: ["main"] })
      } else if (url.match(/\/repositories\/[0-9a-f-]{36}$/)) {
        route.fulfill({ json: MOCK_REPO })
      } else {
        route.fulfill({ json: [MOCK_REPO] })
      }
    })
    await page.route("**/api/v1/analyses/**", (route) => {
      route.fulfill({ status: 500, json: { detail: "Internal error" } })
    })

    await page.goto(`/repositories/${MOCK_REPO.id}`)

    await expect(page.getByText(/no analyses|error/i).first()).toBeVisible({
      timeout: 15000,
    })
    await expect(page.locator("body")).not.toContainText("Unhandled")
  })

  test("rules API 500 shows empty state not crash", async ({ page }) => {
    await page.route("**/api/v1/rules/**", (route) => {
      route.fulfill({ status: 500, json: { detail: "Internal error" } })
    })

    await page.goto("/rules")

    await expect(page.locator("body")).not.toContainText("Something went wrong")
    await expect(page.locator("body")).not.toContainText("Unhandled")
  })

  test("network timeout on analyses shows retry or empty state", async ({
    page,
  }) => {
    await page.route("**/api/v1/repositories/**", (route) => {
      const url = route.request().url()
      if (url.includes("/branches")) {
        route.fulfill({ json: ["main"] })
      } else if (url.match(/\/repositories\/[0-9a-f-]{36}$/)) {
        route.fulfill({ json: MOCK_REPO })
      } else {
        route.fulfill({ json: [MOCK_REPO] })
      }
    })
    await page.route("**/api/v1/analyses/**", async (route) => {
      await new Promise((r) => setTimeout(r, 3000))
      route.fulfill({ json: [] })
    })

    await page.goto(`/repositories/${MOCK_REPO.id}`)

    await expect(
      page
        .locator(".animate-pulse, [data-loading]")
        .or(page.getByText("No analyses found"))
        .first(),
    ).toBeVisible({
      timeout: 10000,
    })
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })
})
