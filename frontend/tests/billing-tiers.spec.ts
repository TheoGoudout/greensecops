import { expect, test } from "@playwright/test"
import {
  MOCK_SUBSCRIPTION,
  MOCK_SUBSCRIPTION_AT_LIMIT,
  MOCK_SUBSCRIPTION_PRO,
  MOCK_TIER_LIMITS,
  MOCK_TIER_LIMITS_PRO,
  mockAnalyses,
  mockEvents,
  mockIssues,
  mockRepositories,
  mockRules,
  mockUserMe,
} from "./utils/mocks"

const MOCK_TIER_LIMITS_ULTIMATE = {
  tier: "ultimate",
  limits: { analyses: 999999, fixes: 999999, repos: 999999 },
}

const MOCK_SUBSCRIPTION_ULTIMATE = {
  ...MOCK_SUBSCRIPTION_PRO,
  tier: "ultimate" as const,
  analyses_used: 120,
  fixes_used: 45,
  repos_used: 8,
}

test.describe("Billing Tiers", () => {
  test.beforeEach(async ({ page }) => {
    await mockUserMe(page)
    await mockEvents(page)
    await mockRules(page)
    await mockRepositories(page, [])
    await mockAnalyses(page, [])
    await mockIssues(page, [])
  })

  test("free tier shows Free label and $0 price", async ({ page }) => {
    await page.route("**/api/v1/billing/**", (route) => {
      const url = route.request().url()
      if (url.includes("/limits")) {
        route.fulfill({ json: MOCK_TIER_LIMITS })
      } else {
        route.fulfill({ json: MOCK_SUBSCRIPTION })
      }
    })

    await page.goto("/billing")

    await expect(page.getByText("Free")).toBeVisible()
    await expect(page.getByText("$0/mo")).toBeVisible()
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("free tier shows usage counts", async ({ page }) => {
    await page.route("**/api/v1/billing/**", (route) => {
      const url = route.request().url()
      if (url.includes("/limits")) {
        route.fulfill({ json: MOCK_TIER_LIMITS })
      } else {
        route.fulfill({ json: MOCK_SUBSCRIPTION })
      }
    })

    await page.goto("/billing")

    await expect(page.getByText(/12.*50|50.*12/).first()).toBeVisible()
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("pro tier shows Pro label", async ({ page }) => {
    await page.route("**/api/v1/billing/**", (route) => {
      const url = route.request().url()
      if (url.includes("/limits")) {
        route.fulfill({ json: MOCK_TIER_LIMITS_PRO })
      } else {
        route.fulfill({ json: MOCK_SUBSCRIPTION_PRO })
      }
    })

    await page.goto("/billing")

    await expect(page.getByText("Pro").first()).toBeVisible()
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("pro tier shows higher limits than free", async ({ page }) => {
    await page.route("**/api/v1/billing/**", (route) => {
      const url = route.request().url()
      if (url.includes("/limits")) {
        route.fulfill({ json: MOCK_TIER_LIMITS_PRO })
      } else {
        route.fulfill({ json: MOCK_SUBSCRIPTION_PRO })
      }
    })

    await page.goto("/billing")

    await expect(page.getByText(/500/).first()).toBeVisible()
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("ultimate tier shows Ultimate label", async ({ page }) => {
    await page.route("**/api/v1/billing/**", (route) => {
      const url = route.request().url()
      if (url.includes("/limits")) {
        route.fulfill({ json: MOCK_TIER_LIMITS_ULTIMATE })
      } else {
        route.fulfill({ json: MOCK_SUBSCRIPTION_ULTIMATE })
      }
    })

    await page.goto("/billing")

    await expect(page.getByText("Ultimate")).toBeVisible()
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("usage at limit shows warning or full state", async ({ page }) => {
    await page.route("**/api/v1/billing/**", (route) => {
      const url = route.request().url()
      if (url.includes("/limits")) {
        route.fulfill({ json: MOCK_TIER_LIMITS })
      } else {
        route.fulfill({ json: MOCK_SUBSCRIPTION_AT_LIMIT })
      }
    })

    await page.goto("/billing")

    await expect(page.getByText(/50.*50|50 \/ 50/).first()).toBeVisible()
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("free tier shows manage subscription button", async ({ page }) => {
    await page.route("**/api/v1/billing/**", (route) => {
      const url = route.request().url()
      if (url.includes("/limits")) {
        route.fulfill({ json: MOCK_TIER_LIMITS })
      } else {
        route.fulfill({ json: MOCK_SUBSCRIPTION })
      }
    })

    await page.goto("/billing")

    await expect(page.getByText("Free")).toBeVisible()
    await expect(
      page.getByRole("button", { name: /manage subscription/i }),
    ).toBeVisible()
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("billing checkout button calls billing API", async ({ page }) => {
    let checkoutCalled = false

    await page.route("**/api/v1/billing/**", (route) => {
      const url = route.request().url()
      const method = route.request().method()
      if (method === "POST" && url.includes("/checkout")) {
        checkoutCalled = true
        route.fulfill({
          json: { checkout_url: "https://checkout.stripe.com/test" },
        })
      } else if (url.includes("/limits")) {
        route.fulfill({ json: MOCK_TIER_LIMITS })
      } else {
        route.fulfill({ json: MOCK_SUBSCRIPTION })
      }
    })

    await page.goto("/billing")

    const checkoutBtn = page.getByRole("button", {
      name: /upgrade|subscribe|get pro/i,
    })
    if (await checkoutBtn.isVisible()) {
      await checkoutBtn.click()
      expect(checkoutCalled).toBe(true)
    }
  })
})
