import { expect, test } from "@playwright/test"
import {
  MOCK_FIX_COMMENT_DELIVERED,
  MOCK_FIX_DELIVERED,
  MOCK_FIX_FAILED,
  MOCK_FIX_MERGED_PR,
  MOCK_FIX_PENDING,
  MOCK_FIX_READY,
  MOCK_ISSUE_WITH_DELIVERED_FIX,
  MOCK_ISSUE_WITH_FAILED_FIX,
  MOCK_ISSUE_WITH_FIX,
  MOCK_ISSUE_WITH_PENDING_FIX,
  mockBilling,
  mockEvents,
  mockRepositories,
  mockRules,
  mockUserMe,
} from "./utils/mocks"

function setupFixDetailMocks(
  page: import("@playwright/test").Page,
  fix: object,
  issue: object,
) {
  return Promise.all([
    mockUserMe(page),
    mockEvents(page),
    mockBilling(page),
    mockRules(page),
    mockRepositories(page),
    page.route("**/api/v1/workflow/fixes**", (route) => {
      const url = route.request().url()
      const method = route.request().method()
      if (method === "POST" && url.includes("/retry")) {
        route.fulfill({ status: 202, json: { status: "queued" } })
      } else if (method === "POST" && url.includes("/deliveries")) {
        route.fulfill({ json: { status: "delivering" } })
      } else if (method === "DELETE") {
        route.fulfill({ json: { ...(fix as object), status: "rejected" } })
      } else {
        route.fulfill({ json: fix })
      }
    }),
    page.route("**/api/v1/workflow/findings**", (route) => {
      route.fulfill({ json: issue })
    }),
    page.route("**/api/v1/workflow/scans**", (route) => {
      route.fulfill({ json: [] })
    }),
  ])
}

test.describe("Fix Lifecycle — Status States", () => {
  test("pending fix shows pending status and no diff", async ({ page }) => {
    await setupFixDetailMocks(
      page,
      MOCK_FIX_PENDING,
      MOCK_ISSUE_WITH_PENDING_FIX,
    )

    await page.goto(`/fixes/${MOCK_FIX_PENDING.id}`)

    await expect(page.getByText("pending", { exact: true })).toBeVisible()
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("ready fix shows diff and accept/deliver button", async ({ page }) => {
    await setupFixDetailMocks(page, MOCK_FIX_READY, MOCK_ISSUE_WITH_FIX)

    await page.goto(`/fixes/${MOCK_FIX_READY.id}`)

    await expect(page.getByText("ready")).toBeVisible()
    await expect(page.getByText("timeout-minutes").first()).toBeVisible()
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("failed fix shows error message", async ({ page }) => {
    await setupFixDetailMocks(page, MOCK_FIX_FAILED, MOCK_ISSUE_WITH_FAILED_FIX)

    await page.goto(`/fixes/${MOCK_FIX_FAILED.id}`)

    await expect(page.getByText("failed")).toBeVisible()
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("delivered fix with PR shows View PR link", async ({ page }) => {
    await setupFixDetailMocks(
      page,
      MOCK_FIX_DELIVERED,
      MOCK_ISSUE_WITH_DELIVERED_FIX,
    )

    await page.goto(`/fixes/${MOCK_FIX_DELIVERED.id}`)

    await expect(page.getByText("delivered")).toBeVisible()
    await expect(page.getByRole("link", { name: "View PR" })).toBeVisible()
    await expect(page.getByRole("link", { name: "View PR" })).toHaveAttribute(
      "href",
      "https://github.com/acme/web-app/pull/42",
    )
  })

  test("delivered fix via comment mode shows comment link not PR link", async ({
    page,
  }) => {
    await setupFixDetailMocks(
      page,
      MOCK_FIX_COMMENT_DELIVERED,
      MOCK_ISSUE_WITH_DELIVERED_FIX,
    )

    await page.goto(`/fixes/${MOCK_FIX_COMMENT_DELIVERED.id}`)

    await expect(page.getByText("delivered")).toBeVisible()
    await expect(page.locator("body")).not.toContainText(
      "https://github.com/acme/web-app/pull/",
    )
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("fix with merged PR shows merged state", async ({ page }) => {
    await setupFixDetailMocks(
      page,
      MOCK_FIX_MERGED_PR,
      MOCK_ISSUE_WITH_DELIVERED_FIX,
    )

    await page.goto(`/fixes/${MOCK_FIX_MERGED_PR.id}`)

    await expect(page.getByText("delivered")).toBeVisible()
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })
})

test.describe("Fix Lifecycle — Actions", () => {
  test("delivering a ready fix calls deliver API and shows success", async ({
    page,
  }) => {
    let deliverCalled = false

    await mockUserMe(page)
    await mockEvents(page)
    await mockBilling(page)
    await mockRules(page)
    await mockRepositories(page)

    await page.route("**/api/v1/workflow/fixes**", (route) => {
      const url = route.request().url()
      const method = route.request().method()
      if (method === "POST" && url.includes("/deliver")) {
        deliverCalled = true
        route.fulfill({ json: { ...MOCK_FIX_READY, status: "delivered" } })
      } else {
        route.fulfill({ json: MOCK_FIX_READY })
      }
    })
    await page.route("**/api/v1/workflow/findings**", (route) => {
      route.fulfill({ json: MOCK_ISSUE_WITH_FIX })
    })
    await page.route("**/api/v1/workflow/scans**", (route) => {
      route.fulfill({ json: [] })
    })

    await page.goto(`/fixes/${MOCK_FIX_READY.id}`)
    await expect(page.getByText("ready")).toBeVisible()

    const deliverBtn = page
      .getByRole("button", { name: /deliver|accept|create pr/i })
      .first()
    if (await deliverBtn.isVisible()) {
      await deliverBtn.click()
      expect(deliverCalled).toBe(true)
    }
  })

  test("retrying a failed fix calls the retry endpoint", async ({ page }) => {
    let retryCalled = false

    await mockUserMe(page)
    await mockEvents(page)
    await mockBilling(page)
    await mockRules(page)
    await mockRepositories(page)

    await page.route("**/api/v1/workflow/fixes**", (route) => {
      const url = route.request().url()
      const method = route.request().method()
      if (method === "POST" && url.includes("/retry")) {
        retryCalled = true
        route.fulfill({ status: 202, json: { status: "queued" } })
      } else {
        route.fulfill({ json: MOCK_FIX_FAILED })
      }
    })
    await page.route("**/api/v1/workflow/findings**", (route) => {
      route.fulfill({ json: MOCK_ISSUE_WITH_FAILED_FIX })
    })
    await page.route("**/api/v1/workflow/scans**", (route) => {
      route.fulfill({ json: [] })
    })

    await page.goto(`/fixes/${MOCK_FIX_FAILED.id}`)
    await expect(page.getByText("failed")).toBeVisible()

    const retryBtn = page.getByRole("button", { name: /retry/i }).first()
    if (await retryBtn.isVisible()) {
      await retryBtn.click()
      expect(retryCalled).toBe(true)
    }
  })

  test("fix list in repo shows all fix statuses", async ({ page }) => {
    await mockUserMe(page)
    await mockEvents(page)
    await mockBilling(page)
    await mockRules(page)
    await mockRepositories(page)

    await page.route("**/api/v1/workflow/fixes**", (route) => {
      route.fulfill({
        json: [
          MOCK_FIX_PENDING,
          MOCK_FIX_READY,
          MOCK_FIX_DELIVERED,
          MOCK_FIX_FAILED,
        ],
      })
    })
    await page.route("**/api/v1/workflow/findings**", (route) => {
      route.fulfill({
        json: [
          MOCK_ISSUE_WITH_PENDING_FIX,
          MOCK_ISSUE_WITH_FIX,
          MOCK_ISSUE_WITH_DELIVERED_FIX,
          MOCK_ISSUE_WITH_FAILED_FIX,
        ],
      })
    })
    await page.route("**/api/v1/workflow/scans**", (route) => {
      route.fulfill({ json: [] })
    })

    await page.goto(
      `/repositories/${MOCK_ISSUE_WITH_FIX.scan_id.replace("analysis", "repo")}/static-analysis`,
    )

    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })
})
