import { expect, test } from "@playwright/test"
import {
  MOCK_ANALYSIS,
  MOCK_FIX_READY,
  MOCK_ISSUE_RELIABILITY,
  MOCK_ISSUE_SECURITY,
  MOCK_REPO,
  MOCK_WORKFLOW_FILE,
  mockBilling,
  mockEvents,
  mockRules,
  mockUserMe,
} from "./utils/mocks"

test.describe("Golden Path — Extended", () => {
  test.beforeEach(async ({ page }) => {
    await mockUserMe(page)
    await mockEvents(page)
    await mockBilling(page)
    await mockRules(page)
  })

  test("repos → trigger → analysis detail → issues → generate fix", async ({
    page,
  }) => {
    await page.route("**/api/v1/repositories**", (route) => {
      const url = route.request().url()
      if (url.includes("/workflow-files")) {
        route.fulfill({ json: [MOCK_WORKFLOW_FILE] })
      } else if (url.includes("/branches")) {
        route.fulfill({ json: ["main"] })
      } else if (url.match(/\/repositories\/[0-9a-f-]{36}$/)) {
        route.fulfill({ json: MOCK_REPO })
      } else {
        route.fulfill({ json: [MOCK_REPO] })
      }
    })

    let analysisTriggered = false
    await page.route("**/api/v1/workflow/scans**", (route) => {
      const method = route.request().method()
      const url = route.request().url()
      if (method === "POST" && url.includes("/repositories/")) {
        analysisTriggered = true
        route.fulfill({
          status: 202,
          json: { status: "queued", repo_id: MOCK_REPO.id },
        })
      } else if (url.match(/\/scans\/[0-9a-f-]{36}$/)) {
        route.fulfill({ json: MOCK_ANALYSIS })
      } else {
        route.fulfill({ json: [MOCK_ANALYSIS] })
      }
    })

    let fixGenerated = false
    await page.route("**/api/v1/workflow/findings**", (route) => {
      route.fulfill({
        json: [MOCK_ISSUE_SECURITY, MOCK_ISSUE_RELIABILITY],
      })
    })
    await page.route("**/api/v1/workflow/fixes**", (route) => {
      const method = route.request().method()
      if (method === "POST") {
        fixGenerated = true
        route.fulfill({ status: 202, json: { status: "queued" } })
      } else {
        route.fulfill({ json: [] })
      }
    })

    await page.goto("/repositories")
    await expect(page.getByText("acme/web-app")).toBeVisible()

    await page.getByRole("button", { name: "Trigger analysis" }).click()
    expect(analysisTriggered).toBe(true)
    await expect(page.getByText("Analysis queued")).toBeVisible()

    await page.getByText("acme/web-app").first().click()
    await expect(page).toHaveURL(
      new RegExp(`/repositories/${MOCK_REPO.id}/static-analysis`),
    )

    // Analysis rows live in the collapsible history; open it and follow the
    // row into the analysis detail page.
    await page.getByRole("button", { name: /Analysis history/ }).click()
    await page
      .getByRole("link", { name: /ci\.yml/ })
      .first()
      .click()
    await expect(page).toHaveURL(new RegExp(`/analyses/${MOCK_ANALYSIS.id}`))

    // `.first()` because the analysis page shows a finding's message twice —
    // once in its row, once as the annotation beside the offending line in the
    // file viewer. Same reason issue-filters.spec.ts does it.
    await expect(
      page
        .getByText("Workflow uses overly permissive token permissions.")
        .first(),
    ).toBeVisible()

    const fixBtn = page.getByRole("button", { name: /fix/i }).first()
    await fixBtn.click()
    expect(fixGenerated).toBe(true)
  })

  test("repo detail: batch fix + workflow PR delivery", async ({ page }) => {
    await page.route("**/api/v1/repositories**", (route) => {
      const url = route.request().url()
      if (url.includes("/workflow-files")) {
        route.fulfill({ json: [MOCK_WORKFLOW_FILE] })
      } else if (url.includes("/branches")) {
        route.fulfill({ json: ["main"] })
      } else if (url.match(/\/repositories\/[0-9a-f-]{36}$/)) {
        route.fulfill({ json: MOCK_REPO })
      } else {
        route.fulfill({ json: [MOCK_REPO] })
      }
    })
    await page.route("**/api/v1/workflow/scans**", (route) => {
      route.fulfill({ json: [MOCK_ANALYSIS] })
    })

    const issues = [MOCK_ISSUE_SECURITY, MOCK_ISSUE_RELIABILITY]
    await page.route("**/api/v1/workflow/findings**", (route) => {
      route.fulfill({ json: issues })
    })

    let batchFixCalled = false
    await page.route("**/api/v1/workflow/fixes**", (route) => {
      const method = route.request().method()
      const url = route.request().url()
      if (method === "POST" && url.includes("generate-for-repo")) {
        batchFixCalled = true
        route.fulfill({
          status: 202,
          json: { queued: 2, skipped: 0 },
        })
      } else if (method === "POST") {
        route.fulfill({ json: { status: "delivering" } })
      } else {
        route.fulfill({ json: [MOCK_FIX_READY] })
      }
    })

    await page.goto(`/repositories/${MOCK_REPO.id}/static-analysis`)

    const fixBtn = page.getByRole("button", { name: /Fix selected/ })
    await expect(fixBtn).toBeVisible()
    await fixBtn.click()
    expect(batchFixCalled).toBe(true)
    await expect(page.getByText(/Queued 2 fix/)).toBeVisible()

    // The ready fix now surfaces in the workflow card footer on the same tab.
    await expect(page.getByText("ready").first()).toBeVisible()
  })

  test("repo detail: integrate action flow", async ({ page }) => {
    await page.route("**/api/v1/repositories**", (route) => {
      const url = route.request().url()
      if (url.includes("/workflow-files")) {
        route.fulfill({ json: [MOCK_WORKFLOW_FILE] })
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
    })
    await page.route("**/api/v1/workflow/scans**", (route) => {
      route.fulfill({ json: [MOCK_ANALYSIS] })
    })
    await page.route("**/api/v1/workflow/findings**", (route) => {
      route.fulfill({ json: [] })
    })
    await page.route("**/api/v1/workflow/fixes**", (route) => {
      route.fulfill({ json: [] })
    })
    await page.route("**/api/v1/telemetry**", (route) => {
      route.fulfill({ json: { runs: [], average: null } })
    })

    // Integrate action lives on the Telemetry tab now.
    await page.goto(`/repositories/${MOCK_REPO.id}/telemetry`)

    await page.getByRole("button", { name: "Integrate action" }).click()

    await expect(page.getByText("PR opened").first()).toBeVisible()
  })
})
