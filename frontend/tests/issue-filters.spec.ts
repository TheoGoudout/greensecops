import { expect, test } from "@playwright/test"
import {
  MOCK_ANALYSIS,
  MOCK_ISSUE_ENERGY,
  MOCK_ISSUE_RELIABILITY,
  MOCK_ISSUE_SECURITY,
  MOCK_ISSUE_WITH_CONTEXT,
  MOCK_ISSUE_WITH_DELIVERED_FIX,
  MOCK_ISSUE_WITH_FAILED_FIX,
  MOCK_ISSUE_WITH_PENDING_FIX,
  MOCK_REPO,
  mockBilling,
  mockEvents,
  mockFixes,
  mockRepositories,
  mockRules,
  mockUserMe,
} from "./utils/mocks"

test.describe("Issue Filters and Display", () => {
  test.beforeEach(async ({ page }) => {
    await mockUserMe(page)
    await mockEvents(page)
    await mockBilling(page)
    await mockRules(page)
    await mockRepositories(page)
    await mockFixes(page, [])
    await page.route("**/api/v1/analyses/**", (route) => {
      route.fulfill({ json: [MOCK_ANALYSIS] })
    })
  })

  test("all issues shown when no filter applied", async ({ page }) => {
    await page.route("**/api/v1/issues/**", (route) => {
      route.fulfill({
        json: [MOCK_ISSUE_SECURITY, MOCK_ISSUE_RELIABILITY, MOCK_ISSUE_ENERGY],
      })
    })

    await page.goto(`/repositories/${MOCK_REPO.id}/static-analysis`)

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

  test("issues display severity labels", async ({ page }) => {
    await page.route("**/api/v1/issues/**", (route) => {
      route.fulfill({
        json: [MOCK_ISSUE_SECURITY, MOCK_ISSUE_RELIABILITY, MOCK_ISSUE_ENERGY],
      })
    })

    await page.goto(`/repositories/${MOCK_REPO.id}/static-analysis`)

    await expect(page.getByText("critical").first()).toBeVisible()
    await expect(page.getByText("high").first()).toBeVisible()
    await expect(page.getByText("medium").first()).toBeVisible()
  })

  test("issues display category icons", async ({ page }) => {
    await page.route("**/api/v1/issues/**", (route) => {
      route.fulfill({
        json: [MOCK_ISSUE_SECURITY, MOCK_ISSUE_RELIABILITY, MOCK_ISSUE_ENERGY],
      })
    })

    await page.goto(`/repositories/${MOCK_REPO.id}/static-analysis`)

    await expect(page.getByText("🔒").first()).toBeVisible()
    await expect(page.getByText("🛡️").first()).toBeVisible()
    await expect(page.getByText("⚡").first()).toBeVisible()
  })

  test("issue with code context shows snippet", async ({ page }) => {
    await page.route("**/api/v1/issues/**", (route) => {
      route.fulfill({ json: [MOCK_ISSUE_WITH_CONTEXT] })
    })

    await page.goto(`/repositories/${MOCK_REPO.id}/static-analysis`)

    await expect(
      page.getByText("Job 'build' has no timeout-minutes set."),
    ).toBeVisible()
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("issue with pending fix renders without per-issue fix status", async ({
    page,
  }) => {
    await page.route("**/api/v1/issues/**", (route) => {
      route.fulfill({ json: [MOCK_ISSUE_WITH_PENDING_FIX] })
    })

    await page.goto(`/repositories/${MOCK_REPO.id}/static-analysis`)

    await expect(
      page.getByText("Workflow uses overly permissive token permissions."),
    ).toBeVisible()
    await expect(page.getByText(/queued/i)).toHaveCount(0)
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("issue with failed fix shows generate fix button", async ({ page }) => {
    await page.route("**/api/v1/issues/**", (route) => {
      route.fulfill({ json: [MOCK_ISSUE_WITH_FAILED_FIX] })
    })

    await page.goto(`/repositories/${MOCK_REPO.id}/static-analysis`)

    await expect(
      page.getByText("Job 'lint' has no timeout-minutes set."),
    ).toBeVisible()
    await expect(
      page.getByRole("button", { name: /generate fix/i }).first(),
    ).toBeVisible()
  })

  test("issue with delivered fix renders without per-issue fix status", async ({
    page,
  }) => {
    await page.route("**/api/v1/issues/**", (route) => {
      route.fulfill({ json: [MOCK_ISSUE_WITH_DELIVERED_FIX] })
    })

    await page.goto(`/repositories/${MOCK_REPO.id}/static-analysis`)

    await expect(
      page.getByText("Job 'deploy' has no timeout-minutes set."),
    ).toBeVisible()
    await expect(page.getByText("delivered")).toHaveCount(0)
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("mix of issue fix statuses all rendered correctly", async ({ page }) => {
    await page.route("**/api/v1/issues/**", (route) => {
      route.fulfill({
        json: [
          MOCK_ISSUE_SECURITY,
          MOCK_ISSUE_WITH_PENDING_FIX,
          MOCK_ISSUE_WITH_FAILED_FIX,
          MOCK_ISSUE_WITH_DELIVERED_FIX,
        ],
      })
    })

    await page.goto(`/repositories/${MOCK_REPO.id}/static-analysis`)

    await expect(
      page
        .getByText("Workflow uses overly permissive token permissions.")
        .first(),
    ).toBeVisible()
    await expect(
      page.getByText("Job 'lint' has no timeout-minutes set."),
    ).toBeVisible()
    await expect(
      page.getByText("Job 'deploy' has no timeout-minutes set."),
    ).toBeVisible()
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("analysis detail shows issues grouped by workflow", async ({ page }) => {
    await page.route("**/api/v1/analyses/**", (route) => {
      const url = route.request().url()
      if (url.match(/\/analyses\/[0-9a-f-]{36}$/)) {
        route.fulfill({ json: MOCK_ANALYSIS })
      } else {
        route.fulfill({ json: [MOCK_ANALYSIS] })
      }
    })
    await page.route("**/api/v1/issues/**", (route) => {
      route.fulfill({
        json: [MOCK_ISSUE_SECURITY, MOCK_ISSUE_RELIABILITY],
      })
    })

    await page.goto(`/analyses/${MOCK_ANALYSIS.id}`)

    await expect(
      page.getByText("Workflow uses overly permissive token permissions."),
    ).toBeVisible()
    await expect(
      page.getByText("Job 'build' has no timeout-minutes set."),
    ).toBeVisible()
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("workflow card renders with no issues when all resolved", async ({
    page,
  }) => {
    await page.route("**/api/v1/issues/**", (route) => {
      route.fulfill({ json: [] })
    })

    await page.goto(`/repositories/${MOCK_REPO.id}/static-analysis`)

    // The workflow file still renders; there are just no issue rows to manage.
    await expect(page.getByText("ci.yml").first()).toBeVisible()
    await expect(page.getByText(/Manage \d+ issue/)).toHaveCount(0)
  })
})
