import { expect, test } from "@playwright/test"
import {
  MOCK_ISSUE_ENERGY,
  MOCK_ISSUE_RELIABILITY,
  MOCK_ISSUE_SECURITY,
  mockAnalyses,
  mockBilling,
  mockEvents,
  mockRepositories,
  mockRules,
  mockUserMe,
} from "./utils/mocks"

test.describe("Issues", () => {
  test.beforeEach(async ({ page }) => {
    await mockUserMe(page)
    await mockEvents(page)
    await mockBilling(page)
    await mockRules(page)
    await mockRepositories(page, [])
    await mockAnalyses(page, [])
  })

  test("loads issue list with severity chip and rule slug", async ({
    page,
  }) => {
    await mockIssuesRoute(page, [
      MOCK_ISSUE_SECURITY,
      MOCK_ISSUE_RELIABILITY,
      MOCK_ISSUE_ENERGY,
    ])

    await page.goto("/issues")

    await expect(page.getByRole("heading", { name: "Issues" })).toBeVisible()
    await expect(page.getByText("excessive_token_permissions")).toBeVisible()
    await expect(page.getByText("missing_timeout")).toBeVisible()
    await expect(page.getByText("caching_missing")).toBeVisible()
    await expect(
      page.getByText("Workflow uses overly permissive token permissions."),
    ).toBeVisible()
  })

  test("category filter dropdown calls API with category param", async ({
    page,
  }) => {
    const apiCalls: string[] = []
    await page.route("**/api/v1/issues/**", (route) => {
      apiCalls.push(route.request().url())
      route.fulfill({ json: [MOCK_ISSUE_SECURITY] })
    })

    await page.goto("/issues")
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

  test("severity filter dropdown calls API with severity param", async ({
    page,
  }) => {
    const apiCalls: string[] = []
    await page.route("**/api/v1/issues/**", (route) => {
      apiCalls.push(route.request().url())
      route.fulfill({ json: [MOCK_ISSUE_RELIABILITY] })
    })

    await page.goto("/issues")
    await page.waitForLoadState("networkidle")

    const severityTrigger = page
      .locator("button")
      .filter({ hasText: "All severities" })
    await severityTrigger.click()
    await page.getByRole("option", { name: "High" }).click()

    await page.waitForTimeout(500)
    const lastCall = apiCalls[apiCalls.length - 1]
    expect(lastCall).toContain("severity=high")
  })

  test("Open only toggle sends unfixed param", async ({ page }) => {
    const apiCalls: string[] = []
    await page.route("**/api/v1/issues/**", (route) => {
      apiCalls.push(route.request().url())
      route.fulfill({ json: [MOCK_ISSUE_SECURITY] })
    })

    await page.goto("/issues")
    await page.waitForLoadState("networkidle")

    await page.getByRole("button", { name: "Open only" }).click()

    await page.waitForTimeout(500)
    const lastCall = apiCalls[apiCalls.length - 1]
    expect(lastCall).toContain("unfixed=true")
  })

  test("empty state when no issues match filters", async ({ page }) => {
    await mockIssuesRoute(page, [])

    await page.goto("/issues")

    await expect(
      page.getByText("No issues match the selected filters."),
    ).toBeVisible()
  })

  test("pagination — Previous disabled on first page, Next navigable", async ({
    page,
  }) => {
    const fiftyIssues = Array.from({ length: 50 }, (_, i) => ({
      ...MOCK_ISSUE_SECURITY,
      id: `00000000-0000-0000-0000-${String(i).padStart(12, "0")}`,
    }))

    const apiCalls: string[] = []
    await page.route("**/api/v1/issues/**", (route) => {
      apiCalls.push(route.request().url())
      route.fulfill({ json: fiftyIssues })
    })

    await page.goto("/issues")
    await page.waitForLoadState("networkidle")

    const prevBtn = page.getByRole("button", { name: "Previous" })
    const nextBtn = page.getByRole("button", { name: "Next" })

    await expect(prevBtn).toBeDisabled()
    await expect(nextBtn).toBeEnabled()

    await nextBtn.click()
    await page.waitForTimeout(500)

    const lastCall = apiCalls[apiCalls.length - 1]
    expect(lastCall).toContain("skip=50")
    await expect(page.getByText("Page 2")).toBeVisible()
    await expect(prevBtn).toBeEnabled()
  })

  test("error state when API fails", async ({ page }) => {
    await page.route("**/api/v1/issues/**", (route) => {
      route.fulfill({ status: 500, json: { detail: "Internal error" } })
    })

    await page.goto("/issues")

    await expect(page.getByText("Failed to load issues.")).toBeVisible({
      timeout: 15000,
    })
  })

  test("Next button disabled when fewer than PAGE_SIZE results", async ({
    page,
  }) => {
    await mockIssuesRoute(page, [MOCK_ISSUE_SECURITY, MOCK_ISSUE_RELIABILITY])

    await page.goto("/issues")

    const nextBtn = page.getByRole("button", { name: "Next" })
    await expect(nextBtn).toBeDisabled()
  })
})

async function mockIssuesRoute(
  page: import("@playwright/test").Page,
  issues: unknown[],
) {
  await page.route("**/api/v1/issues/**", (route) => {
    route.fulfill({ json: issues })
  })
}
