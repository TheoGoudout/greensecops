import { expect, test } from "@playwright/test"
import {
  MOCK_ANALYSIS,
  MOCK_FIX_DELIVERED,
  MOCK_FIX_READY,
  MOCK_ISSUE_ENERGY,
  MOCK_ISSUE_RELIABILITY,
  MOCK_ISSUE_SECURITY,
  MOCK_ISSUE_WITH_FIX,
  MOCK_PR_OPEN,
  MOCK_REPO,
  MOCK_WORKFLOW_FILE,
  mockBilling,
  mockEvents,
  mockRules,
  mockUserMe,
} from "./utils/mocks"

test.describe("Repository Detail", () => {
  test.beforeEach(async ({ page }) => {
    await mockUserMe(page)
    await mockEvents(page)
    await mockBilling(page)
    await mockRules(page)
  })

  function setupRepoMocks(
    page: import("@playwright/test").Page,
    opts: {
      analyses?: unknown[]
      issues?: unknown[]
      fixes?: unknown[]
      workflowFiles?: unknown[]
      pullRequests?: unknown[]
    } = {},
  ) {
    const {
      analyses = [MOCK_ANALYSIS],
      issues = [MOCK_ISSUE_SECURITY, MOCK_ISSUE_RELIABILITY, MOCK_ISSUE_ENERGY],
      fixes = [],
      workflowFiles = [MOCK_WORKFLOW_FILE],
      pullRequests = [],
    } = opts

    return Promise.all([
      page.route("**/api/v1/repositories/**", (route) => {
        const url = route.request().url()
        if (url.includes("/workflow-files")) {
          route.fulfill({ json: workflowFiles })
        } else if (url.includes("/integrate-action")) {
          route.fulfill({
            json: { pr_url: "https://github.com/acme/web-app/pull/99" },
          })
        } else if (url.includes("/branches")) {
          route.fulfill({ json: ["main"] })
        } else if (url.match(/\/repositories\/[0-9a-f-]{36}$/)) {
          route.fulfill({ json: MOCK_REPO })
        } else {
          route.fulfill({ json: [MOCK_REPO] })
        }
      }),
      page.route("**/api/v1/analyses/**", (route) => {
        const url = route.request().url()
        const method = route.request().method()
        if (method === "POST" && url.includes("/trigger/")) {
          route.fulfill({
            status: 202,
            json: { status: "queued", repo_id: MOCK_REPO.id },
          })
        } else if (url.match(/\/analyses\/[0-9a-f-]{36}$/)) {
          route.fulfill({ json: analyses[0] })
        } else {
          route.fulfill({ json: analyses })
        }
      }),
      page.route("**/api/v1/issues/**", (route) => {
        route.fulfill({ json: issues })
      }),
      page.route("**/api/v1/fixes/**", (route) => {
        const url = route.request().url()
        const method = route.request().method()
        if (method === "POST" && url.includes("/sync-pr-status")) {
          route.fulfill({ json: { synced: 0, updated: 0, relinked: 0 } })
        } else if (method === "POST" && url.includes("for-repo")) {
          route.fulfill({
            status: 202,
            json: { queued: issues.length, skipped: 0 },
          })
        } else if (method === "POST" && url.includes("/deliver")) {
          route.fulfill({ json: { status: "delivering" } })
        } else if (url.includes("/pull-requests/")) {
          route.fulfill({ json: pullRequests })
        } else if (url.match(/\/fixes\/[0-9a-f-]{36}$/)) {
          const id = url.split("/").pop()
          const fix = fixes.find((f: any) => f.id === id) ?? fixes[0]
          route.fulfill({ json: fix })
        } else {
          route.fulfill({ json: fixes })
        }
      }),
    ])
  }

  test("header shows repo name, grade, and default branch", async ({
    page,
  }) => {
    await setupRepoMocks(page)

    await page.goto(`/repositories/${MOCK_REPO.id}`)

    await expect(page.getByText("acme/web-app")).toBeVisible()
    await expect(
      page.getByRole("combobox").filter({ hasText: "main" }),
    ).toBeVisible()
  })

  test("Static analysis tab shows workflow card with status", async ({
    page,
  }) => {
    await setupRepoMocks(page)

    await page.goto(`/repositories/${MOCK_REPO.id}`)

    // Default route redirects to the merged Static analysis tab.
    await expect(page).toHaveURL(new RegExp(`/${MOCK_REPO.id}/static-analysis`))
    await expect(page.getByText("ci.yml").first()).toBeVisible()
    await expect(page.getByText("completed").first()).toBeVisible()
  })

  test("Static analysis shows issues inside the workflow card", async ({
    page,
  }) => {
    await setupRepoMocks(page)

    await page.goto(`/repositories/${MOCK_REPO.id}/static-analysis`)

    await expect(
      page
        .getByText("Workflow uses overly permissive token permissions.")
        .first(),
    ).toBeVisible()
  })

  test("Static analysis empty state when no workflow files", async ({
    page,
  }) => {
    await setupRepoMocks(page, { workflowFiles: [] })

    await page.goto(`/repositories/${MOCK_REPO.id}/static-analysis`)

    await expect(page.getByText("No workflow files found")).toBeVisible()
  })

  test("Analysis history section lists analyses", async ({ page }) => {
    await setupRepoMocks(page)

    await page.goto(`/repositories/${MOCK_REPO.id}/static-analysis`)

    await page.getByRole("button", { name: /Analysis history/ }).click()
    await expect(page.getByText("manual")).toBeVisible()
  })

  test("Fix selected button queues fixes", async ({ page }) => {
    const issues = [MOCK_ISSUE_SECURITY, MOCK_ISSUE_RELIABILITY]
    await setupRepoMocks(page, { issues })

    await page.goto(`/repositories/${MOCK_REPO.id}/static-analysis`)

    const fixBtn = page.getByRole("button", { name: /Fix selected/ })
    await expect(fixBtn).toBeVisible()
    await fixBtn.click()

    await expect(page.getByText(/Queued 2 fix/)).toBeVisible()
  })

  test("Static analysis shows fix status and View PR in the card", async ({
    page,
  }) => {
    await setupRepoMocks(page, {
      issues: [MOCK_ISSUE_WITH_FIX],
      fixes: [MOCK_FIX_READY],
    })

    await page.goto(`/repositories/${MOCK_REPO.id}/static-analysis`)

    await expect(page.getByText("ready").first()).toBeVisible()
  })

  test("Create PR for all workflows button delivers repo-wide", async ({
    page,
  }) => {
    let deliverCalled = false
    await page.route("**/api/v1/repositories/**", (route) => {
      const url = route.request().url()
      if (url.includes("/workflow-files")) {
        route.fulfill({ json: [MOCK_WORKFLOW_FILE] })
      } else if (url.includes("/branches")) {
        route.fulfill({ json: ["main"] })
      } else {
        route.fulfill({ json: MOCK_REPO })
      }
    })
    await page.route("**/api/v1/analyses/**", (route) => {
      route.fulfill({ json: [MOCK_ANALYSIS] })
    })
    await page.route("**/api/v1/issues/**", (route) => {
      route.fulfill({ json: [MOCK_ISSUE_WITH_FIX] })
    })
    await page.route("**/api/v1/fixes/**", (route) => {
      const url = route.request().url()
      const method = route.request().method()
      if (method === "POST" && url.includes("deliver-for-repo")) {
        deliverCalled = true
        route.fulfill({ json: { status: "delivering" } })
      } else if (url.includes("/pull-requests/")) {
        route.fulfill({ json: [] })
      } else {
        route.fulfill({ json: [MOCK_FIX_READY] })
      }
    })

    await page.goto(`/repositories/${MOCK_REPO.id}/static-analysis`)

    const btn = page.getByRole("button", {
      name: "Create PR for all workflows",
    })
    await expect(btn).toBeVisible()
    await btn.click()

    expect(deliverCalled).toBe(true)
    await expect(page.getByText("Repo-wide PR queued")).toBeVisible()
  })

  test("PRs tab shows pull requests", async ({ page }) => {
    await setupRepoMocks(page, {
      fixes: [MOCK_FIX_DELIVERED],
      pullRequests: [MOCK_PR_OPEN],
    })

    await page.goto(`/repositories/${MOCK_REPO.id}/pull-requests`)

    await expect(page.getByText("acme/web-app/pull/42")).toBeVisible()
    await expect(page.getByText("open").first()).toBeVisible()
  })

  test("PRs tab empty state", async ({ page }) => {
    await setupRepoMocks(page, { fixes: [], pullRequests: [] })

    await page.goto(`/repositories/${MOCK_REPO.id}/pull-requests`)

    await expect(
      page.getByText("No GreenSecOps-created PRs yet."),
    ).toBeVisible()
  })

  test("Run analysis button triggers analysis", async ({ page }) => {
    await setupRepoMocks(page)

    await page.goto(`/repositories/${MOCK_REPO.id}`)

    await page.getByRole("button", { name: "Run analysis" }).click()

    await expect(page.getByText("Analysis queued")).toBeVisible()
  })

  test("Integrate action button triggers PR", async ({ page }) => {
    await setupRepoMocks(page)
    // Integrate action lives on the Telemetry tab now.
    await page.route("**/api/v1/telemetry/**", (route) => {
      route.fulfill({ json: { runs: [], average: null } })
    })

    await page.goto(`/repositories/${MOCK_REPO.id}/telemetry`)

    await page.getByRole("button", { name: "Integrate action" }).click()

    await expect(page.getByText("PR opened").first()).toBeVisible()
  })
})
