import { expect, test } from "@playwright/test"
import {
  MOCK_ANALYSIS_FAILED,
  MOCK_ANALYSIS_PENDING,
  MOCK_REPO,
  MOCK_REPO_DISABLED,
  MOCK_REPO_EXTERNAL,
  MOCK_REPO_NO_ANALYSES,
  MOCK_WORKFLOW_FILE,
  mockBilling,
  mockEvents,
  mockFixes,
  mockIssues,
  mockRules,
  mockUserMe,
} from "./utils/mocks"

test.describe("Repository Edge Cases", () => {
  test.beforeEach(async ({ page }) => {
    await mockUserMe(page)
    await mockEvents(page)
    await mockBilling(page)
    await mockRules(page)
    await mockIssues(page, [])
    await mockFixes(page, [])
  })

  test("external repo shows in repository list", async ({ page }) => {
    await page.route(/\/api\/v1\/(workflow\/)?repositories\b/, (route) => {
      const url = route.request().url()
      if (url.includes("/pull-requests")) {
        route.fulfill({ json: [] })
      } else if (url.match(/\/repositories\/[0-9a-f-]{36}$/)) {
        route.fulfill({ json: MOCK_REPO_EXTERNAL })
      } else {
        route.fulfill({ json: [MOCK_REPO, MOCK_REPO_EXTERNAL] })
      }
    })
    await page.route(/\/api\/v1\/workflow\/(repositories\/[^/]+\/)?scans/, (route) => {
      route.fulfill({ json: [] })
    })

    await page.goto("/repositories")

    await expect(page.getByText("external/third-party-repo")).toBeVisible()
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("external repo detail page loads without crash", async ({ page }) => {
    await page.route(/\/api\/v1\/(workflow\/)?repositories\b/, (route) => {
      const url = route.request().url()
      if (url.includes("/pull-requests")) {
        route.fulfill({ json: [] })
      } else if (url.includes("/files")) {
        route.fulfill({ json: [] })
      } else if (url.includes("/branches")) {
        route.fulfill({ json: ["main"] })
      } else {
        route.fulfill({ json: MOCK_REPO_EXTERNAL })
      }
    })
    await page.route(/\/api\/v1\/workflow\/(repositories\/[^/]+\/)?scans/, (route) => {
      route.fulfill({ json: [] })
    })

    await page.goto(`/repositories/${MOCK_REPO_EXTERNAL.id}`)

    await expect(page.getByText("external/third-party-repo")).toBeVisible()
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("disabled repo shows as disabled in list", async ({ page }) => {
    await page.route(/\/api\/v1\/(workflow\/)?repositories\b/, (route) => {
      const url = route.request().url()
      if (url.includes("/pull-requests")) {
        route.fulfill({ json: [] })
      } else if (url.match(/\/repositories\/[0-9a-f-]{36}$/)) {
        route.fulfill({ json: MOCK_REPO_DISABLED })
      } else {
        route.fulfill({ json: [MOCK_REPO_DISABLED] })
      }
    })
    await page.route(/\/api\/v1\/workflow\/(repositories\/[^/]+\/)?scans/, (route) => {
      route.fulfill({ json: [] })
    })

    await page.goto("/repositories")

    await expect(page.getByText("acme/old-service")).toBeVisible()
    const toggle = page.locator("button[role='switch']").first()
    await expect(toggle).toBeVisible()
    await expect(toggle).toHaveAttribute("aria-checked", "false")
  })

  test("repo with no analyses shows no grade", async ({ page }) => {
    await page.route(/\/api\/v1\/(workflow\/)?repositories\b/, (route) => {
      const url = route.request().url()
      if (url.includes("/pull-requests")) {
        route.fulfill({ json: [] })
      } else if (url.includes("/files")) {
        route.fulfill({ json: [] })
      } else if (url.includes("/branches")) {
        route.fulfill({ json: ["main"] })
      } else if (url.match(/\/repositories\/[0-9a-f-]{36}$/)) {
        route.fulfill({ json: MOCK_REPO_NO_ANALYSES })
      } else {
        route.fulfill({ json: [MOCK_REPO_NO_ANALYSES] })
      }
    })
    await page.route(/\/api\/v1\/workflow\/(repositories\/[^/]+\/)?scans/, (route) => {
      route.fulfill({ json: [] })
    })

    await page.goto(`/repositories/${MOCK_REPO_NO_ANALYSES.id}`)

    await expect(page.getByText("acme/new-repo")).toBeVisible()
    await expect(page.getByText("No workflow files found")).toBeVisible()
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("repo with failed analysis shows failed status in list", async ({
    page,
  }) => {
    await page.route(/\/api\/v1\/(workflow\/)?repositories\b/, (route) => {
      const url = route.request().url()
      if (url.includes("/pull-requests")) {
        route.fulfill({ json: [] })
      } else if (url.includes("/files")) {
        route.fulfill({ json: [MOCK_WORKFLOW_FILE] })
      } else if (url.includes("/branches")) {
        route.fulfill({ json: ["main"] })
      } else if (url.match(/\/repositories\/[0-9a-f-]{36}$/)) {
        route.fulfill({ json: MOCK_REPO })
      } else {
        route.fulfill({ json: [MOCK_REPO] })
      }
    })
    await page.route(/\/api\/v1\/workflow\/(repositories\/[^/]+\/)?scans/, (route) => {
      const url = route.request().url()
      if (url.match(/\/scans\/[0-9a-f-]{36}$/)) {
        route.fulfill({ json: MOCK_ANALYSIS_FAILED })
      } else {
        route.fulfill({ json: [MOCK_ANALYSIS_FAILED] })
      }
    })

    await page.goto(`/repositories/${MOCK_REPO.id}`)

    // The workflow card surfaces the file's latest analysis status.
    await expect(page.getByText("failed").first()).toBeVisible()
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("repo with pending analysis shows pending status", async ({ page }) => {
    await page.route(/\/api\/v1\/(workflow\/)?repositories\b/, (route) => {
      const url = route.request().url()
      if (url.includes("/pull-requests")) {
        route.fulfill({ json: [] })
      } else if (url.includes("/files")) {
        route.fulfill({ json: [MOCK_WORKFLOW_FILE] })
      } else if (url.includes("/branches")) {
        route.fulfill({ json: ["main"] })
      } else if (url.match(/\/repositories\/[0-9a-f-]{36}$/)) {
        route.fulfill({ json: MOCK_REPO })
      } else {
        route.fulfill({ json: [MOCK_REPO] })
      }
    })
    await page.route(/\/api\/v1\/workflow\/(repositories\/[^/]+\/)?scans/, (route) => {
      const url = route.request().url()
      if (url.match(/\/scans\/[0-9a-f-]{36}$/)) {
        route.fulfill({ json: MOCK_ANALYSIS_PENDING })
      } else {
        route.fulfill({ json: [MOCK_ANALYSIS_PENDING] })
      }
    })

    await page.goto(`/repositories/${MOCK_REPO.id}`)

    // The workflow card surfaces the file's latest analysis status.
    await expect(page.getByText("pending").first()).toBeVisible()
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("enabling a disabled repo calls toggle API", async ({ page }) => {
    let toggleCalled = false

    await page.route(/\/api\/v1\/(workflow\/)?repositories\b/, (route) => {
      const url = route.request().url()
      const method = route.request().method()
      if (method === "PATCH") {
        toggleCalled = true
        route.fulfill({
          json: { ...MOCK_REPO_DISABLED, enabled: true },
        })
      } else if (url.match(/\/repositories\/[0-9a-f-]{36}$/)) {
        route.fulfill({ json: MOCK_REPO_DISABLED })
      } else {
        route.fulfill({ json: [MOCK_REPO_DISABLED] })
      }
    })
    await page.route(/\/api\/v1\/workflow\/(repositories\/[^/]+\/)?scans/, (route) => {
      route.fulfill({ json: [] })
    })

    await page.goto("/repositories")

    const toggle = page.locator("button[role='switch']").first()
    await toggle.click()

    expect(toggleCalled).toBe(true)
  })

  test("mixed list of enabled, disabled and external repos all render", async ({
    page,
  }) => {
    await page.route(/\/api\/v1\/(workflow\/)?repositories\b/, (route) => {
      const url = route.request().url()
      if (url.includes("/pull-requests")) {
        route.fulfill({ json: [] })
      } else if (url.match(/\/repositories\/[0-9a-f-]{36}$/)) {
        route.fulfill({ json: MOCK_REPO })
      } else {
        route.fulfill({
          json: [MOCK_REPO, MOCK_REPO_DISABLED, MOCK_REPO_EXTERNAL],
        })
      }
    })
    await page.route(/\/api\/v1\/workflow\/(repositories\/[^/]+\/)?scans/, (route) => {
      route.fulfill({ json: [] })
    })

    await page.goto("/repositories")

    await expect(page.getByText("acme/web-app")).toBeVisible()
    await expect(page.getByText("acme/old-service")).toBeVisible()
    await expect(page.getByText("external/third-party-repo")).toBeVisible()
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })
})
