import { expect, test } from "@playwright/test"
import {
  MOCK_ANALYSIS,
  MOCK_ISSUE_ENERGY,
  MOCK_ISSUE_RELIABILITY,
  MOCK_ISSUE_SECURITY,
  mockBilling,
  mockEvents,
  mockFixes,
  mockRepositories,
  mockRules,
  mockUserMe,
} from "./utils/mocks"

test.describe("Analysis Detail", () => {
  test.beforeEach(async ({ page }) => {
    await mockUserMe(page)
    await mockEvents(page)
    await mockBilling(page)
    await mockRules(page)
    await mockRepositories(page)
    await mockFixes(page, [])
  })

  test("shows metadata: grade, score, status, branch, workflow", async ({
    page,
  }) => {
    await page.route("**/api/v1/workflow-scans/**", (route) => {
      route.fulfill({ json: MOCK_ANALYSIS })
    })
    await page.route("**/api/v1/workflow-findings/**", (route) => {
      route.fulfill({ json: [] })
    })

    await page.goto(`/analyses/${MOCK_ANALYSIS.id}`)

    await expect(page.getByText("Analysis Detail")).toBeVisible()
    await expect(page.getByText("82/100")).toBeVisible()
    await expect(page.getByText("completed")).toBeVisible()
    await expect(page.getByText("main")).toBeVisible()
    await expect(page.getByText(".github/workflows/ci.yml")).toBeVisible()
  })

  test("issues grouped by category", async ({ page }) => {
    await page.route("**/api/v1/workflow-scans/**", (route) => {
      route.fulfill({ json: MOCK_ANALYSIS })
    })
    await page.route("**/api/v1/workflow-findings/**", (route) => {
      route.fulfill({
        json: [MOCK_ISSUE_SECURITY, MOCK_ISSUE_RELIABILITY, MOCK_ISSUE_ENERGY],
      })
    })

    await page.goto(`/analyses/${MOCK_ANALYSIS.id}`)

    await expect(
      page.getByText("Workflow uses overly permissive token permissions."),
    ).toBeVisible()
    await expect(
      page.getByText("Job 'build' has no timeout-minutes set."),
    ).toBeVisible()
    await expect(
      page.getByText("No caching configured for dependencies."),
    ).toBeVisible()
  })

  test("Generate fix button visible per issue", async ({ page }) => {
    await page.route("**/api/v1/workflow-scans/**", (route) => {
      route.fulfill({ json: MOCK_ANALYSIS })
    })
    await page.route("**/api/v1/workflow-findings/**", (route) => {
      route.fulfill({ json: [MOCK_ISSUE_SECURITY] })
    })

    await page.goto(`/analyses/${MOCK_ANALYSIS.id}`)

    await expect(
      page.getByRole("button", { name: /fix/i }).first(),
    ).toBeVisible()
  })

  test("empty issues state", async ({ page }) => {
    await page.route("**/api/v1/workflow-scans/**", (route) => {
      route.fulfill({ json: MOCK_ANALYSIS })
    })
    await page.route("**/api/v1/workflow-findings/**", (route) => {
      route.fulfill({ json: [] })
    })

    await page.goto(`/analyses/${MOCK_ANALYSIS.id}`)

    await expect(
      page.getByText("No issues found for this analysis."),
    ).toBeVisible()
  })

  test("invalid analysis ID shows error alert", async ({ page }) => {
    await page.route("**/api/v1/workflow-scans/**", (route) => {
      route.fulfill({ status: 404, json: { detail: "Not found" } })
    })
    await page.route("**/api/v1/workflow-findings/**", (route) => {
      route.fulfill({ json: [] })
    })

    await page.goto("/analyses/00000000-0000-0000-0000-999999999999")

    await expect(
      page.getByText("Analysis not found or failed to load."),
    ).toBeVisible({ timeout: 15000 })
  })
})
