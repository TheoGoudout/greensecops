import { expect, test } from "@playwright/test"
import {
  MOCK_RULE_DISABLED,
  MOCK_RULE_RELIABILITY,
  MOCK_RULE_SECURITY,
  MOCK_SUPERUSER,
  MOCK_USER,
  mockAnalyses,
  mockBilling,
  mockEvents,
  mockIssues,
  mockRepositories,
  mockUserMe,
} from "./utils/mocks"

test.describe("Rules", () => {
  test.beforeEach(async ({ page }) => {
    await mockEvents(page)
    await mockBilling(page)
    await mockRepositories(page, [])
    await mockAnalyses(page, [])
    await mockIssues(page, [])
  })

  test("shows rules with slug, description, and severity", async ({
    page,
  }) => {
    await mockUserMe(page, MOCK_SUPERUSER)
    await mockRulesRoute(page, [
      MOCK_RULE_SECURITY,
      MOCK_RULE_RELIABILITY,
      MOCK_RULE_DISABLED,
    ])

    await page.goto("/rules")

    await expect(page.getByRole("heading", { name: "Rules" })).toBeVisible()
    await expect(
      page.getByText("excessive_token_permissions"),
    ).toBeVisible()
    await expect(page.getByText("missing_timeout")).toBeVisible()
    await expect(page.getByText("caching_missing")).toBeVisible()
    await expect(
      page.getByText(
        "Workflow uses overly permissive GITHUB_TOKEN permissions.",
        { exact: false },
      ),
    ).toBeVisible()
  })

  test("category filter dropdown filters rules", async ({ page }) => {
    await mockUserMe(page, MOCK_SUPERUSER)

    const apiCalls: string[] = []
    await page.route("**/api/v1/rules/**", (route) => {
      apiCalls.push(route.request().url())
      route.fulfill({ json: [MOCK_RULE_SECURITY] })
    })

    await page.goto("/rules")
    await page.waitForLoadState("networkidle")

    const categoryTrigger = page
      .locator("button")
      .filter({ hasText: "All categories" })
    await categoryTrigger.click()
    await page.getByRole("option", { name: /Security/ }).click()

    await page.waitForTimeout(500)
    const lastCall = apiCalls[apiCalls.length - 1]
    expect(lastCall).toContain("category=security")
  })

  test("superuser can toggle rules", async ({ page }) => {
    await mockUserMe(page, MOCK_SUPERUSER)

    let toggleCalled = false
    await page.route("**/api/v1/rules/**", (route) => {
      const url = route.request().url()
      if (url.includes("/toggle")) {
        toggleCalled = true
        route.fulfill({
          json: { ...MOCK_RULE_SECURITY, enabled: false },
        })
      } else {
        route.fulfill({
          json: [MOCK_RULE_SECURITY, MOCK_RULE_RELIABILITY],
        })
      }
    })

    await page.goto("/rules")

    await expect(
      page.getByText("View and toggle analysis rules (superuser)"),
    ).toBeVisible()

    const switchEl = page.locator("button[role='switch']").first()
    await expect(switchEl).toBeEnabled()
    await switchEl.click()

    expect(toggleCalled).toBe(true)
  })

  test("regular user sees disabled switches", async ({ page }) => {
    await mockUserMe(page, MOCK_USER)
    await mockRulesRoute(page, [MOCK_RULE_SECURITY])

    await page.goto("/rules")

    await expect(
      page.getByText("View analysis rules and their severities"),
    ).toBeVisible()

    const switchEl = page.locator("button[role='switch']").first()
    await expect(switchEl).toBeDisabled()
  })

  test("empty state when no rules", async ({ page }) => {
    await mockUserMe(page, MOCK_SUPERUSER)
    await mockRulesRoute(page, [])

    await page.goto("/rules")

    await expect(page.getByText("No rules found.")).toBeVisible()
  })
})

async function mockRulesRoute(
  page: import("@playwright/test").Page,
  rules: unknown[],
) {
  await page.route("**/api/v1/rules/**", (route) => {
    route.fulfill({ json: rules })
  })
}
