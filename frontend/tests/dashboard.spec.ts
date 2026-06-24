import { expect, test } from "@playwright/test"
import {
  MOCK_ANALYSIS,
  MOCK_ISSUE_ENERGY,
  MOCK_ISSUE_RELIABILITY,
  MOCK_ISSUE_SECURITY,
  MOCK_REPO,
  MOCK_REPO_DISABLED,
  mockAnalyses,
  mockBilling,
  mockEvents,
  mockIssues,
  mockRepositories,
  mockRules,
  mockUserMe,
} from "./utils/mocks"

test.describe("Dashboard", () => {
  test.beforeEach(async ({ page }) => {
    await mockUserMe(page)
    await mockEvents(page)
    await mockBilling(page)
    await mockRules(page)
  })

  test("displays stat cards with computed values", async ({ page }) => {
    await mockRepositories(page, [MOCK_REPO, MOCK_REPO_DISABLED])
    await mockAnalyses(page, [MOCK_ANALYSIS])
    await mockIssues(page, [
      MOCK_ISSUE_SECURITY,
      MOCK_ISSUE_RELIABILITY,
      MOCK_ISSUE_ENERGY,
    ])

    await page.goto("/dashboard")

    await expect(page.getByText("Total analyses")).toBeVisible()
    await expect(page.getByText("Active repositories")).toBeVisible()
    await expect(page.getByText("Average score")).toBeVisible()
    await expect(page.getByText("Open issues")).toBeVisible()

    const activeCard = page.locator("text=Active repositories").locator("..")
    await expect(activeCard.locator("..")).toContainText("1")
    await expect(page.getByText("of 2 connected")).toBeVisible()

    await expect(page.getByText("82/100").first()).toBeVisible({
      timeout: 10000,
    })

    await expect(page.getByText("1 critical")).toBeVisible()
  })

  test("recent analyses table shows repo name, grade, and score", async ({
    page,
  }) => {
    await mockRepositories(page, [MOCK_REPO])
    await mockAnalyses(page, [MOCK_ANALYSIS])
    await mockIssues(page, [])

    await page.goto("/dashboard")

    await expect(page.getByText("Recent Analyses")).toBeVisible()
    await expect(page.getByText("acme/web-app")).toBeVisible()
    await expect(page.getByText("a1b2c3d")).toBeVisible()
    await expect(page.getByText("82/100").first()).toBeVisible({
      timeout: 10000,
    })
  })

  test("empty state when no analyses", async ({ page }) => {
    await mockRepositories(page, [MOCK_REPO])
    await mockAnalyses(page, [])
    await mockIssues(page, [])

    await page.goto("/dashboard")

    await expect(
      page.getByText(
        "No analyses yet. Trigger one from the Repositories page.",
      ),
    ).toBeVisible()
  })

  test("empty state when no repos shows 0 connected", async ({ page }) => {
    await mockRepositories(page, [])
    await mockAnalyses(page, [])
    await mockIssues(page, [])

    await page.goto("/dashboard")

    await expect(page.getByText("of 0 connected")).toBeVisible()
  })

  test("clicking analysis row navigates to detail", async ({ page }) => {
    await mockRepositories(page, [MOCK_REPO])
    await mockAnalyses(page, [MOCK_ANALYSIS])
    await mockIssues(page, [])

    await page.goto("/dashboard")

    await page.getByText("acme/web-app").click()

    await expect(page).toHaveURL(new RegExp(`/analyses/${MOCK_ANALYSIS.id}`))
  })

  test("/ redirects to /dashboard", async ({ page }) => {
    await mockRepositories(page, [])
    await mockAnalyses(page, [])
    await mockIssues(page, [])

    await page.goto("/")

    await expect(page).toHaveURL(/\/dashboard/)
  })

  test("loading skeletons appear while data loads", async ({ page }) => {
    await mockRepositories(page, [MOCK_REPO])
    await mockIssues(page, [])
    await page.route("**/api/v1/analyses/**", async (route) => {
      await new Promise((r) => setTimeout(r, 2000))
      route.fulfill({ json: [] })
    })

    await page.goto("/dashboard")

    await expect(page.locator(".animate-pulse").first()).toBeVisible()
  })

  test("stat card shows critical count in hint", async ({ page }) => {
    await mockRepositories(page, [MOCK_REPO])
    await mockAnalyses(page, [MOCK_ANALYSIS])
    await mockIssues(page, [
      MOCK_ISSUE_SECURITY,
      { ...MOCK_ISSUE_SECURITY, id: "00000000-0000-0000-0000-000000000099" },
    ])

    await page.goto("/dashboard")

    await expect(page.getByText("2 critical")).toBeVisible()
  })
})
