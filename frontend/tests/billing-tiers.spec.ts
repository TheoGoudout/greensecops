import { expect, test } from "@playwright/test"
import {
  MOCK_SUBSCRIPTION,
  MOCK_SUBSCRIPTION_AT_LIMIT,
  MOCK_SUBSCRIPTION_PRO,
  MOCK_TIER_LIMITS,
  MOCK_TIER_LIMITS_PRO,
  MOCK_USAGE,
  MOCK_USAGE_AT_LIMIT,
  MOCK_USAGE_PRO,
  mockAnalyses,
  mockBilling,
  mockEvents,
  mockIssues,
  mockRepositories,
  mockRules,
  mockUserMe,
} from "./utils/mocks"

const MOCK_TIER_LIMITS_ULTIMATE = {
  tier: "ultimate",
  limits: { analyses: null, fixes: null, repos: null },
}

const MOCK_SUBSCRIPTION_ULTIMATE = {
  ...MOCK_SUBSCRIPTION_PRO,
  tier: "ultimate" as const,
  effective_tier: "ultimate" as const,
  analyses_used: 120,
  fixes_used: 45,
  repos_used: 8,
}

const MOCK_USAGE_ULTIMATE = {
  ...MOCK_USAGE,
  analyses_used: 120,
  fixes_used: 45,
  repos_used: 8,
  limits: { analyses: null, fixes: null, repos: null },
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
    await mockBilling(page)

    await page.goto("/billing")

    await expect(page.getByText("Free").first()).toBeVisible()
    await expect(page.getByText("$0/mo").first()).toBeVisible()
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("free tier shows usage against the published limits", async ({
    page,
  }) => {
    await mockBilling(page)

    await page.goto("/billing")

    // 12 of 100 — the numbers in backend/app/core/plans.py, which are also what
    // the marketing page renders.
    await expect(page.getByText("12").first()).toBeVisible()
    await expect(page.getByText("/ 100")).toBeVisible()
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("pro tier shows Pro label and its higher limits", async ({ page }) => {
    await mockBilling(
      page,
      MOCK_SUBSCRIPTION_PRO,
      MOCK_TIER_LIMITS_PRO,
      MOCK_USAGE_PRO,
    )

    await page.goto("/billing")

    await expect(page.getByText("Pro").first()).toBeVisible()
    await expect(page.getByText("/ 10,000")).toBeVisible()
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("ultimate tier renders unlimited as ∞, not a huge number", async ({
    page,
  }) => {
    await mockBilling(
      page,
      MOCK_SUBSCRIPTION_ULTIMATE,
      MOCK_TIER_LIMITS_ULTIMATE,
      MOCK_USAGE_ULTIMATE,
    )

    await page.goto("/billing")

    await expect(page.getByText("Ultimate").first()).toBeVisible()
    // `null` means unlimited all the way from the catalog to the bar.
    await expect(page.getByText("/ ∞").first()).toBeVisible()
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("usage at the limit shows the full state", async ({ page }) => {
    await mockBilling(
      page,
      MOCK_SUBSCRIPTION_AT_LIMIT,
      MOCK_TIER_LIMITS,
      MOCK_USAGE_AT_LIMIT,
    )

    await page.goto("/billing")

    await expect(page.getByText("100").first()).toBeVisible()
    await expect(page.getByText("/ 100")).toBeVisible()
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("plan cards are rendered from the catalog", async ({ page }) => {
    await mockBilling(page)

    await page.goto("/billing")

    // Served by GET /billing/plans rather than hard-coded in the frontend, so
    // the app and the marketing site cannot disagree about what a plan costs.
    await expect(page.getByRole("heading", { name: "Plans" })).toBeVisible()
    await expect(page.getByText("$19/mo")).toBeVisible()
    await expect(page.getByText("$79/mo")).toBeVisible()
    await expect(page.getByText("$299/mo")).toBeVisible()
    // "Current plan" is also the usage card's title; mean the badge.
    await expect(
      page.locator('[data-slot="badge"]').filter({ hasText: "Current plan" }),
    ).toBeVisible()
  })

  test("upgrade button calls checkout", async ({ page }) => {
    let checkoutCalled = false

    await page.route("**/api/v1/billing/**", (route) => {
      const url = route.request().url()
      if (route.request().method() === "POST" && url.includes("/checkout")) {
        checkoutCalled = true
        route.fulfill({
          json: { url: "https://checkout.stripe.com/c/pay/test" },
        })
      } else if (url.includes("/limits")) {
        route.fulfill({ json: MOCK_TIER_LIMITS })
      } else if (url.includes("/usage")) {
        route.fulfill({ json: MOCK_USAGE })
      } else if (url.includes("/plans")) {
        route.fulfill({
          json: [
            {
              tier: "pro",
              name: "Pro",
              price_cents: 7900,
              price_display: "$79/mo",
              tagline: "Growing teams.",
              limits: { analyses: 10000, fixes: 1000, repos: 100 },
              auto_fix: true,
              public_repos_only: false,
              is_purchasable: true,
              features: [],
            },
          ],
        })
      } else if (
        url.includes("/invoices") ||
        url.includes("/oss-application")
      ) {
        route.fulfill({ json: [] })
      } else {
        route.fulfill({ json: MOCK_SUBSCRIPTION })
      }
    })

    await page.goto("/billing")

    const upgrade = page.getByRole("button", { name: "Upgrade to Pro" })
    await expect(upgrade).toBeVisible()
    await upgrade.click()
    await expect.poll(() => checkoutCalled).toBe(true)
  })
})
