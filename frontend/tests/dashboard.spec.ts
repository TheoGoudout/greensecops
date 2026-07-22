import { expect, test } from "@playwright/test"
import {
  MOCK_ANALYSIS,
  MOCK_ISSUE_ENERGY,
  MOCK_ISSUE_RELIABILITY,
  MOCK_ISSUE_SECURITY,
  MOCK_REPO,
  MOCK_REPO_DISABLED,
  MOCK_REPO_NO_ANALYSES,
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
    await expect(page.getByText("Open issues")).toBeVisible()
    await expect(page.getByText("Fix rate")).toBeVisible()
    await expect(page.getByText("Avg score:")).toBeVisible()

    const activeCard = page.locator("text=Active repositories").locator("..")
    await expect(activeCard.locator("..")).toContainText("1")
    await expect(page.getByText("of 2 connected")).toBeVisible()

    await expect(page.getByText("82/100").first()).toBeVisible({
      timeout: 10000,
    })

    await expect(page.getByText("1 critical")).toBeVisible()
  })

  test("repository health table shows repo name, grade, and score", async ({
    page,
  }) => {
    await mockRepositories(page, [MOCK_REPO])
    await mockAnalyses(page, [MOCK_ANALYSIS])
    await mockIssues(page, [])

    await page.goto("/dashboard")

    await expect(page.getByText("Repository Health")).toBeVisible()
    await expect(page.getByText("acme/web-app")).toBeVisible()
    await expect(page.getByText("82/100").first()).toBeVisible({
      timeout: 10000,
    })
  })

  test("empty state when no analyses", async ({ page }) => {
    await mockRepositories(page, [MOCK_REPO])
    await mockAnalyses(page, [])
    await mockIssues(page, [])

    await page.goto("/dashboard")

    await expect(page.getByText("No completed analyses yet.")).toBeVisible()
  })

  test("empty state when no repos shows 0 connected", async ({ page }) => {
    await mockRepositories(page, [])
    await mockAnalyses(page, [])
    await mockIssues(page, [])

    await page.goto("/dashboard")

    await expect(page.getByText("of 0 connected")).toBeVisible()
  })

  test("clicking repository health row navigates to repo analyses", async ({
    page,
  }) => {
    await mockRepositories(page, [MOCK_REPO])
    await mockAnalyses(page, [MOCK_ANALYSIS])
    await mockIssues(page, [])

    await page.goto("/dashboard")

    await page.getByText("acme/web-app").click()

    await expect(page).toHaveURL(
      new RegExp(`/repositories/${MOCK_REPO.id}/static-analysis`),
    )
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

  test("category health renders a star diagram axis per category", async ({
    page,
  }) => {
    await mockRepositories(page, [MOCK_REPO])
    await mockAnalyses(page, [MOCK_ANALYSIS])
    await mockIssues(page, [
      MOCK_ISSUE_SECURITY,
      MOCK_ISSUE_RELIABILITY,
      MOCK_ISSUE_ENERGY,
    ])

    await page.goto("/dashboard")

    await expect(page.getByText("Category Health")).toBeVisible()
    const radar = page.getByRole("img", {
      name: "Category health by repository",
    })
    await expect(radar).toBeVisible()
    for (const label of [
      "Energy",
      "Reliability",
      "Security",
      "Performance",
      "Maintainability",
    ]) {
      await expect(radar.getByText(label)).toBeVisible()
    }
  })

  test("category health excludes repos with no workflows (grade N/A)", async ({
    page,
  }) => {
    // listRepositories returns the literal string "N/A" (never null) for a
    // repo with no CI workflows at all — MOCK_REPO_NO_ANALYSES predates that
    // and stubs grade: null, so build the real shape here.
    const repoNoWorkflows = {
      ...MOCK_REPO_NO_ANALYSES,
      grade: "N/A" as const,
    }

    await mockRepositories(page, [MOCK_REPO, repoNoWorkflows])
    await mockAnalyses(page, [MOCK_ANALYSIS])
    await mockIssues(page, [MOCK_ISSUE_SECURITY])

    await page.goto("/dashboard")

    const legend = page.getByTestId("category-health-legend")
    await expect(legend.getByText(MOCK_REPO.full_name)).toBeVisible()
    await expect(legend.getByText(repoNoWorkflows.full_name)).not.toBeAttached()
    await expect(
      page.locator(`path[data-repo-id="${repoNoWorkflows.id}"]`),
    ).not.toBeAttached()
  })

  test("toggling a repo checkbox shows/hides its polygon", async ({ page }) => {
    const repoB = {
      ...MOCK_REPO,
      id: "00000000-0000-0000-0000-000000000200",
      full_name: "acme/api-service",
    }
    const analysisB = {
      ...MOCK_ANALYSIS,
      id: "00000000-0000-0000-0000-000000000201",
      repo_id: repoB.id,
    }
    const issueB = {
      ...MOCK_ISSUE_ENERGY,
      id: "00000000-0000-0000-0000-000000000202",
      analysis_id: analysisB.id,
    }

    await mockRepositories(page, [MOCK_REPO, repoB])
    await mockAnalyses(page, [MOCK_ANALYSIS, analysisB])
    await mockIssues(
      page,
      [MOCK_ISSUE_SECURITY, issueB],
      [MOCK_ANALYSIS, analysisB],
    )

    await page.goto("/dashboard")

    const polygonA = page.locator(`path[data-repo-id="${MOCK_REPO.id}"]`)
    const polygonB = page.locator(`path[data-repo-id="${repoB.id}"]`)
    await expect(polygonA).toBeAttached()
    await expect(polygonB).toBeAttached()

    await page.getByLabel(MOCK_REPO.full_name).uncheck()

    await expect(polygonA).not.toBeAttached()
    await expect(polygonB).toBeAttached()
  })

  test("hovering a repo name dims other repos in the star diagram", async ({
    page,
  }) => {
    const repoB = {
      ...MOCK_REPO,
      id: "00000000-0000-0000-0000-000000000200",
      full_name: "acme/api-service",
    }
    const analysisB = {
      ...MOCK_ANALYSIS,
      id: "00000000-0000-0000-0000-000000000201",
      repo_id: repoB.id,
    }
    const issueB = {
      ...MOCK_ISSUE_ENERGY,
      id: "00000000-0000-0000-0000-000000000202",
      analysis_id: analysisB.id,
    }

    await mockRepositories(page, [MOCK_REPO, repoB])
    await mockAnalyses(page, [MOCK_ANALYSIS, analysisB])
    await mockIssues(
      page,
      [MOCK_ISSUE_SECURITY, issueB],
      [MOCK_ANALYSIS, analysisB],
    )

    await page.goto("/dashboard")

    const polygonA = page.locator(`path[data-repo-id="${MOCK_REPO.id}"]`)
    const polygonB = page.locator(`path[data-repo-id="${repoB.id}"]`)
    const legend = page.getByTestId("category-health-legend")

    await legend.getByText(repoB.full_name).hover()

    await expect
      .poll(() => polygonA.evaluate((el) => getComputedStyle(el).opacity))
      .toBe("0.15")
    await expect
      .poll(() => polygonB.evaluate((el) => getComputedStyle(el).opacity))
      .toBe("1")
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

  test("repository health table paginates past 8 repos", async ({ page }) => {
    const repos = []
    const analyses = []
    for (let i = 0; i < 10; i++) {
      const id = `00000000-0000-0000-0000-00000000030${i}`
      repos.push({ ...MOCK_REPO, id, full_name: `acme/service-${i}` })
      analyses.push({ ...MOCK_ANALYSIS, id: `${id}a`, repo_id: id })
    }

    await mockRepositories(page, repos)
    await mockAnalyses(page, analyses)
    await mockIssues(page, [])

    await page.goto("/dashboard")

    const healthCard = page.getByText("Repository Health").locator("../..")
    await expect(healthCard.getByText("acme/service-0")).toBeVisible()
    await expect(healthCard.getByText("acme/service-8")).not.toBeVisible()
    await expect(healthCard.getByText("Showing 1-8 of 10")).toBeVisible()

    await healthCard.getByRole("button", { name: "Go to next page" }).click()

    await expect(healthCard.getByText("acme/service-0")).not.toBeVisible()
    await expect(healthCard.getByText("acme/service-8")).toBeVisible()
    await expect(healthCard.getByText("Showing 9-10 of 10")).toBeVisible()
  })

  test("repository health pagination hidden at 8 or fewer repos", async ({
    page,
  }) => {
    await mockRepositories(page, [MOCK_REPO])
    await mockAnalyses(page, [MOCK_ANALYSIS])
    await mockIssues(page, [])

    await page.goto("/dashboard")

    await expect(page.getByText("Repository Health")).toBeVisible()
    await expect(page.getByText(/^Showing/)).not.toBeVisible()
  })

  test("category health legend paginates past 8 repos", async ({ page }) => {
    const repos = []
    const analyses = []
    const issues = []
    for (let i = 0; i < 10; i++) {
      const id = `00000000-0000-0000-0000-00000000030${i}`
      repos.push({ ...MOCK_REPO, id, full_name: `acme/service-${i}` })
      analyses.push({ ...MOCK_ANALYSIS, id: `${id}a`, repo_id: id })
      issues.push({
        ...MOCK_ISSUE_ENERGY,
        id: `${id}b`,
        analysis_id: `${id}a`,
      })
    }

    await mockRepositories(page, repos)
    await mockAnalyses(page, analyses)
    await mockIssues(page, issues, analyses)

    await page.goto("/dashboard")

    const legend = page.getByTestId("category-health-legend")
    await expect(legend.getByText("acme/service-0")).toBeVisible()
    await expect(legend.getByText("acme/service-8")).not.toBeVisible()

    const legendPagination = legend.locator("..")
    await legendPagination
      .getByRole("button", { name: "Go to next page" })
      .click()

    await expect(legend.getByText("acme/service-0")).not.toBeVisible()
    await expect(legend.getByText("acme/service-8")).toBeVisible()
  })
})
