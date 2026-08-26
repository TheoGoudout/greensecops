import { expect, test } from "@playwright/test"
import {
  MOCK_ANALYSIS,
  MOCK_ANALYSIS_FAILED,
  MOCK_ANALYSIS_GRADE_A,
  MOCK_ANALYSIS_GRADE_F,
  MOCK_ANALYSIS_IN_PROGRESS,
  MOCK_ANALYSIS_PENDING,
  MOCK_REPO,
  mockBilling,
  mockEvents,
  mockFixes,
  mockIssues,
  mockRepositories,
  mockRules,
  mockUserMe,
} from "./utils/mocks"

test.describe("Analysis States", () => {
  test.beforeEach(async ({ page }) => {
    await mockUserMe(page)
    await mockEvents(page)
    await mockBilling(page)
    await mockRules(page)
    await mockRepositories(page)
    await mockFixes(page, [])
    await mockIssues(page, [])
  })

  test("pending analysis shows status badge and no score", async ({ page }) => {
    await page.route("**/api/v1/workflow-scans/**", (route) => {
      route.fulfill({ json: MOCK_ANALYSIS_PENDING })
    })

    await page.goto(`/analyses/${MOCK_ANALYSIS_PENDING.id}`)

    await expect(page.getByText("pending", { exact: true })).toBeVisible()
    await expect(page.locator("body")).not.toContainText(/\d+\/100/)
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("in_progress analysis shows status and no score", async ({ page }) => {
    await page.route("**/api/v1/workflow-scans/**", (route) => {
      route.fulfill({ json: MOCK_ANALYSIS_IN_PROGRESS })
    })

    await page.goto(`/analyses/${MOCK_ANALYSIS_IN_PROGRESS.id}`)

    await expect(page.getByText("in_progress")).toBeVisible()
    await expect(page.locator("body")).not.toContainText(/\d+\/100/)
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("failed analysis shows error message and failed status", async ({
    page,
  }) => {
    await page.route("**/api/v1/workflow-scans/**", (route) => {
      route.fulfill({ json: MOCK_ANALYSIS_FAILED })
    })

    await page.goto(`/analyses/${MOCK_ANALYSIS_FAILED.id}`)

    await expect(page.getByText("failed")).toBeVisible()
    await expect(page.locator("body")).not.toContainText(/\d+\/100/)
  })

  test("grade-A analysis shows 100/100 score and A badge", async ({ page }) => {
    await page.route("**/api/v1/workflow-scans/**", (route) => {
      route.fulfill({ json: MOCK_ANALYSIS_GRADE_A })
    })

    await page.goto(`/analyses/${MOCK_ANALYSIS_GRADE_A.id}`)

    await expect(page.getByText("100/100")).toBeVisible()
    await expect(page.getByText(/^A$/).first()).toBeVisible()
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("grade-F analysis shows low score and F badge", async ({ page }) => {
    await page.route("**/api/v1/workflow-scans/**", (route) => {
      route.fulfill({ json: MOCK_ANALYSIS_GRADE_F })
    })

    await page.goto(`/analyses/${MOCK_ANALYSIS_GRADE_F.id}`)

    await expect(page.getByText("12/100")).toBeVisible()
    await expect(page.getByText(/^F$/).first()).toBeVisible()
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("analysis detail shows workflow file path", async ({ page }) => {
    await page.route("**/api/v1/workflow-scans/**", (route) => {
      route.fulfill({ json: MOCK_ANALYSIS })
    })

    await page.goto(`/analyses/${MOCK_ANALYSIS.id}`)

    await expect(page.getByText("ci.yml")).toBeVisible()
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("analysis detail shows branch and commit info", async ({ page }) => {
    await page.route("**/api/v1/workflow-scans/**", (route) => {
      route.fulfill({ json: MOCK_ANALYSIS })
    })

    await page.goto(`/analyses/${MOCK_ANALYSIS.id}`)

    await expect(page.getByText("main")).toBeVisible()
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("repo analysis list shows multiple statuses", async ({ page }) => {
    await page.route("**/api/v1/workflow-scans/**", (route) => {
      const url = route.request().url()
      if (url.match(/\/analyses\/[0-9a-f-]{36}$/)) {
        route.fulfill({ json: MOCK_ANALYSIS })
      } else {
        route.fulfill({
          json: [
            MOCK_ANALYSIS_PENDING,
            MOCK_ANALYSIS_FAILED,
            MOCK_ANALYSIS_GRADE_A,
          ],
        })
      }
    })

    await page.goto(`/repositories/${MOCK_REPO.id}`)

    // The per-run analysis list is now the collapsible "Analysis history".
    await page.getByRole("button", { name: /Analysis history/ }).click()
    await expect(page.getByText("pending").first()).toBeVisible()
    await expect(page.getByText("failed").first()).toBeVisible()
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("two workflow files produce separate rows in repo analysis list", async ({
    page,
  }) => {
    const analysisFile2 = {
      ...MOCK_ANALYSIS,
      id: "00000000-0000-0000-0000-000000000099",
      file_path: ".github/workflows/deploy.yml",
      workflow_file_id: "00000000-0000-0000-0000-000000000031",
    }

    await page.route("**/api/v1/workflow-scans/**", (route) => {
      const url = route.request().url()
      if (url.match(/\/analyses\/[0-9a-f-]{36}$/)) {
        route.fulfill({ json: MOCK_ANALYSIS })
      } else {
        route.fulfill({ json: [MOCK_ANALYSIS, analysisFile2] })
      }
    })

    await page.goto(`/repositories/${MOCK_REPO.id}`)

    // Both files appear as rows in the collapsible "Analysis history".
    await page.getByRole("button", { name: /Analysis history/ }).click()
    await expect(page.getByText("ci.yml").first()).toBeVisible()
    await expect(page.getByText("deploy.yml").first()).toBeVisible()
  })
})
