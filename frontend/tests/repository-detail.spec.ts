import { expect, test } from "@playwright/test"
import {
  MOCK_ANALYSIS,
  MOCK_FIX_DELIVERED,
  MOCK_FIX_READY,
  MOCK_ISSUE_ENERGY,
  MOCK_ISSUE_RELIABILITY,
  MOCK_ISSUE_SECURITY,
  MOCK_ISSUE_WITH_FIX,
  MOCK_REPO,
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
    } = {},
  ) {
    const {
      analyses = [MOCK_ANALYSIS],
      issues = [MOCK_ISSUE_SECURITY, MOCK_ISSUE_RELIABILITY, MOCK_ISSUE_ENERGY],
      fixes = [],
    } = opts

    return Promise.all([
      page.route("**/api/v1/repositories/**", (route) => {
        const url = route.request().url()
        if (url.includes("/integrate-action")) {
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
        if (method === "POST" && url.includes("for-repo")) {
          route.fulfill({
            status: 202,
            json: { queued: issues.length, skipped: 0 },
          })
        } else if (method === "POST" && url.includes("/deliver")) {
          route.fulfill({ json: { status: "delivering" } })
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

  test("Analyses tab shows analysis rows", async ({ page }) => {
    await setupRepoMocks(page)

    await page.goto(`/repositories/${MOCK_REPO.id}`)

    await expect(page.getByText("completed")).toBeVisible()
    await expect(page.getByText("ci.yml")).toBeVisible()
  })

  test("Analyses tab empty state", async ({ page }) => {
    await setupRepoMocks(page, { analyses: [] })

    await page.goto(`/repositories/${MOCK_REPO.id}`)

    await expect(page.getByText("No analyses found")).toBeVisible()
  })

  test("Issues tab shows issues grouped by workflow", async ({ page }) => {
    await setupRepoMocks(page)

    await page.goto(`/repositories/${MOCK_REPO.id}/issues`)

    await expect(page.getByText("Workflow:")).toBeVisible()
    await expect(page.getByText("ci.yml")).toBeVisible()
    await expect(
      page.getByText("Workflow uses overly permissive token permissions."),
    ).toBeVisible()
  })

  test("Issues tab checkbox selection and Fix selected button", async ({
    page,
  }) => {
    const issues = [MOCK_ISSUE_SECURITY, MOCK_ISSUE_RELIABILITY]
    let fixCalled = false
    await mockUserMe(page)
    await page.route("**/api/v1/repositories/**", (route) => {
      if (route.request().url().includes("/branches")) {
        route.fulfill({ json: ["main"] })
      } else {
        route.fulfill({ json: MOCK_REPO })
      }
    })
    await page.route("**/api/v1/analyses/**", (route) => {
      route.fulfill({ json: [MOCK_ANALYSIS] })
    })
    await page.route("**/api/v1/issues/**", (route) => {
      route.fulfill({ json: issues })
    })
    await page.route("**/api/v1/fixes/**", (route) => {
      const method = route.request().method()
      if (method === "POST") {
        fixCalled = true
        route.fulfill({
          status: 202,
          json: { queued: 2, skipped: 0 },
        })
      } else {
        route.fulfill({ json: [] })
      }
    })

    await page.goto(`/repositories/${MOCK_REPO.id}/issues`)

    const fixBtn = page.getByRole("button", { name: /Fix selected/ })
    await expect(fixBtn).toBeVisible()
    await fixBtn.click()

    expect(fixCalled).toBe(true)
    await expect(page.getByText(/Queued 2 fix/)).toBeVisible()
  })

  test("Issues tab empty state", async ({ page }) => {
    await setupRepoMocks(page, { issues: [] })

    await page.goto(`/repositories/${MOCK_REPO.id}/issues`)

    await expect(page.getByText("No issues found.")).toBeVisible()
  })

  test("Fixes tab shows fixes with status and View PR link", async ({
    page,
  }) => {
    await setupRepoMocks(page, {
      issues: [MOCK_ISSUE_WITH_FIX, MOCK_ISSUE_RELIABILITY],
      fixes: [MOCK_FIX_READY, MOCK_FIX_DELIVERED],
    })

    await page.goto(`/repositories/${MOCK_REPO.id}/fixes`)

    await expect(page.getByText("ready").first()).toBeVisible()
    await expect(page.getByText("delivered").first()).toBeVisible()
    await expect(page.getByRole("link", { name: "View PR" })).toBeVisible()
  })

  test("Fixes tab Create PR for all workflows button", async ({ page }) => {
    let deliverCalled = false
    await page.route("**/api/v1/repositories/**", (route) => {
      if (route.request().url().includes("/branches")) {
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
      } else {
        route.fulfill({ json: [MOCK_FIX_READY] })
      }
    })

    await page.goto(`/repositories/${MOCK_REPO.id}/fixes`)

    const btn = page.getByRole("button", {
      name: "Create PR for all workflows",
    })
    await expect(btn).toBeVisible()
    await btn.click()

    expect(deliverCalled).toBe(true)
    await expect(page.getByText("Repo-wide PR queued")).toBeVisible()
  })

  test("Fixes tab empty state", async ({ page }) => {
    await setupRepoMocks(page, { fixes: [] })

    await page.goto(`/repositories/${MOCK_REPO.id}/fixes`)

    await expect(page.getByText("No fixes yet.")).toBeVisible()
  })

  test("Pull Requests tab shows PRs", async ({ page }) => {
    await setupRepoMocks(page, {
      issues: [MOCK_ISSUE_RELIABILITY],
      fixes: [MOCK_FIX_DELIVERED],
    })

    await page.goto(`/repositories/${MOCK_REPO.id}/pull-requests`)

    await expect(page.getByText("acme/web-app/pull/42")).toBeVisible()
    await expect(page.getByText("open").first()).toBeVisible()
  })

  test("Pull Requests tab empty state", async ({ page }) => {
    await setupRepoMocks(page, { fixes: [] })

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

    await page.goto(`/repositories/${MOCK_REPO.id}`)

    await page.getByRole("button", { name: "Integrate action" }).click()

    await expect(page.getByText("PR opened").first()).toBeVisible()
  })
})
