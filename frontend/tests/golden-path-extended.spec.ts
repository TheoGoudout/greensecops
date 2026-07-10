import { expect, test } from "@playwright/test"
import {
  MOCK_ANALYSIS,
  MOCK_FIX_READY,
  MOCK_ISSUE_RELIABILITY,
  MOCK_ISSUE_SECURITY,
  MOCK_REPO,
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
    await page.route("**/api/v1/repositories/**", (route) => {
      const url = route.request().url()
      if (url.includes("/branches")) {
        route.fulfill({ json: ["main"] })
      } else if (url.match(/\/repositories\/[0-9a-f-]{36}$/)) {
        route.fulfill({ json: MOCK_REPO })
      } else {
        route.fulfill({ json: [MOCK_REPO] })
      }
    })

    let analysisTriggered = false
    await page.route("**/api/v1/analyses/**", (route) => {
      const method = route.request().method()
      const url = route.request().url()
      if (method === "POST" && url.includes("/trigger/")) {
        analysisTriggered = true
        route.fulfill({
          status: 202,
          json: { status: "queued", repo_id: MOCK_REPO.id },
        })
      } else if (url.match(/\/analyses\/[0-9a-f-]{36}$/)) {
        route.fulfill({ json: MOCK_ANALYSIS })
      } else {
        route.fulfill({ json: [MOCK_ANALYSIS] })
      }
    })

    let fixGenerated = false
    await page.route("**/api/v1/issues/**", (route) => {
      route.fulfill({
        json: [MOCK_ISSUE_SECURITY, MOCK_ISSUE_RELIABILITY],
      })
    })
    await page.route("**/api/v1/fixes/**", (route) => {
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
    await expect(page).toHaveURL(new RegExp(`/repositories/${MOCK_REPO.id}`))

    await page.getByText("ci.yml").first().click()
    await expect(page).toHaveURL(new RegExp(`/analyses/${MOCK_ANALYSIS.id}`))

    await expect(
      page.getByText("Workflow uses overly permissive token permissions."),
    ).toBeVisible()

    const fixBtn = page.getByRole("button", { name: /fix/i }).first()
    await fixBtn.click()
    expect(fixGenerated).toBe(true)
  })

  test("repo detail: batch fix + workflow PR delivery", async ({ page }) => {
    await page.route("**/api/v1/repositories/**", (route) => {
      const url = route.request().url()
      if (url.includes("/branches")) {
        route.fulfill({ json: ["main"] })
      } else if (url.match(/\/repositories\/[0-9a-f-]{36}$/)) {
        route.fulfill({ json: MOCK_REPO })
      } else {
        route.fulfill({ json: [MOCK_REPO] })
      }
    })
    await page.route("**/api/v1/analyses/**", (route) => {
      route.fulfill({ json: [MOCK_ANALYSIS] })
    })

    const issues = [MOCK_ISSUE_SECURITY, MOCK_ISSUE_RELIABILITY]
    await page.route("**/api/v1/issues/**", (route) => {
      route.fulfill({ json: issues })
    })

    let batchFixCalled = false
    await page.route("**/api/v1/fixes/**", (route) => {
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

    await page.goto(`/repositories/${MOCK_REPO.id}/issues`)

    const fixBtn = page.getByRole("button", { name: /Fix selected/ })
    await expect(fixBtn).toBeVisible()
    await fixBtn.click()
    expect(batchFixCalled).toBe(true)
    await expect(page.getByText(/Queued 2 fix/)).toBeVisible()

    await page.goto(`/repositories/${MOCK_REPO.id}/fixes`)
    await expect(page.getByText("ready").first()).toBeVisible()
  })

  test("repo detail: integrate action flow", async ({ page }) => {
    await page.route("**/api/v1/repositories/**", (route) => {
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
    })
    await page.route("**/api/v1/analyses/**", (route) => {
      route.fulfill({ json: [MOCK_ANALYSIS] })
    })
    await page.route("**/api/v1/issues/**", (route) => {
      route.fulfill({ json: [] })
    })
    await page.route("**/api/v1/fixes/**", (route) => {
      route.fulfill({ json: [] })
    })

    await page.goto(`/repositories/${MOCK_REPO.id}`)

    await page.getByRole("button", { name: "Integrate action" }).click()

    await expect(page.getByText("PR opened").first()).toBeVisible()
  })
})
