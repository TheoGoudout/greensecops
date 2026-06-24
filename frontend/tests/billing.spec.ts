import { expect, test } from "@playwright/test"
import {
  MOCK_SUBSCRIPTION,
  MOCK_TIER_LIMITS,
  mockAnalyses,
  mockEvents,
  mockIssues,
  mockRepositories,
  mockRules,
  mockUserMe,
} from "./utils/mocks"

test.describe("Billing", () => {
  test.beforeEach(async ({ page }) => {
    await mockUserMe(page)
    await mockEvents(page)
    await mockRules(page)
    await mockRepositories(page, [])
    await mockAnalyses(page, [])
    await mockIssues(page, [])
  })

  test("shows plan name, price, and Active badge", async ({ page }) => {
    await mockBillingRoute(page, MOCK_SUBSCRIPTION, MOCK_TIER_LIMITS)

    await page.goto("/billing")

    await expect(page.getByRole("heading", { name: "Billing" })).toBeVisible()
    await expect(page.getByText("Free")).toBeVisible()
    await expect(page.getByText("$0/mo")).toBeVisible()
    await expect(page.getByText("Active")).toBeVisible()
  })

  test("usage bars show analyses, fixes, repos", async ({ page }) => {
    await mockBillingRoute(page, MOCK_SUBSCRIPTION, MOCK_TIER_LIMITS)

    await page.goto("/billing")

    await expect(page.getByText("Analyses")).toBeVisible()
    await expect(page.getByText("12")).toBeVisible()
    await expect(page.getByText("/ 50")).toBeVisible()

    await expect(page.getByText("AI Fixes")).toBeVisible()
    await expect(page.getByText("2")).toBeVisible()
    await expect(page.getByText("/ 5")).toBeVisible()

    await expect(page.getByText("Repositories")).toBeVisible()
    await expect(page.getByText("/ 3")).toBeVisible()
  })

  test("Manage subscription button is disabled", async ({ page }) => {
    await mockBillingRoute(page, MOCK_SUBSCRIPTION, MOCK_TIER_LIMITS)

    await page.goto("/billing")

    await expect(
      page.getByRole("button", { name: "Manage subscription" }),
    ).toBeDisabled()
  })

  test("loading skeletons appear while data loads", async ({ page }) => {
    await page.route("**/api/v1/billing/**", async (route) => {
      await new Promise((r) => setTimeout(r, 2000))
      route.fulfill({ json: MOCK_SUBSCRIPTION })
    })

    await page.goto("/billing")

    await expect(page.locator(".animate-pulse").first()).toBeVisible()
  })
})

async function mockBillingRoute(
  page: import("@playwright/test").Page,
  subscription: unknown,
  limits: unknown,
) {
  await page.route("**/api/v1/billing/**", (route) => {
    const url = route.request().url()
    if (url.includes("/limits")) {
      route.fulfill({ json: limits })
    } else {
      route.fulfill({ json: subscription })
    }
  })
}
