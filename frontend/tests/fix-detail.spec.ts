import { expect, test } from "@playwright/test"
import {
  MOCK_FIX_DELIVERED,
  MOCK_FIX_READY,
  MOCK_ISSUE_RELIABILITY,
  MOCK_ISSUE_WITH_FIX,
  mockBilling,
  mockEvents,
  mockRepositories,
  mockRules,
  mockUserMe,
} from "./utils/mocks"

test.describe("Fix Detail", () => {
  test.beforeEach(async ({ page }) => {
    await mockUserMe(page)
    await mockEvents(page)
    await mockBilling(page)
    await mockRules(page)
    await mockRepositories(page)
  })

  test("shows fix metadata: status badge, issue info, LLM model", async ({
    page,
  }) => {
    await page.route(/\/api\/v1\/workflow\/(fixes|repositories\/[^/]+\/(fixes|deliveries))/, (route) => {
      route.fulfill({ json: MOCK_FIX_READY })
    })
    await page.route("**/api/v1/workflow/findings**", (route) => {
      route.fulfill({ json: MOCK_ISSUE_WITH_FIX })
    })

    await page.goto(`/fixes/${MOCK_FIX_READY.id}`)

    await expect(page.getByText("Fix Detail")).toBeVisible()
    await expect(page.getByText("ready")).toBeVisible()
    await expect(page.getByText("missing_timeout")).toBeVisible()
    await expect(page.getByText("gpt-4o-mini")).toBeVisible()
  })

  test("ready fix shows Reject and Create PR buttons", async ({ page }) => {
    await page.route(/\/api\/v1\/workflow\/(fixes|repositories\/[^/]+\/(fixes|deliveries))/, (route) => {
      route.fulfill({ json: MOCK_FIX_READY })
    })
    await page.route("**/api/v1/workflow/findings**", (route) => {
      route.fulfill({ json: MOCK_ISSUE_WITH_FIX })
    })

    await page.goto(`/fixes/${MOCK_FIX_READY.id}`)

    await expect(page.getByRole("button", { name: "Reject" })).toBeVisible()
    await expect(page.getByRole("button", { name: "Create PR" })).toBeVisible()
  })

  test("reject calls API and shows toast", async ({ page }) => {
    let deleteCalled = false
    await page.route(/\/api\/v1\/workflow\/(fixes|repositories\/[^/]+\/(fixes|deliveries))/, (route) => {
      if (route.request().method() === "DELETE") {
        deleteCalled = true
        route.fulfill({ status: 204 })
      } else {
        route.fulfill({ json: MOCK_FIX_READY })
      }
    })
    await page.route("**/api/v1/workflow/findings**", (route) => {
      route.fulfill({ json: MOCK_ISSUE_WITH_FIX })
    })

    await page.goto(`/fixes/${MOCK_FIX_READY.id}`)

    await page.getByRole("button", { name: "Reject" }).click()

    expect(deleteCalled).toBe(true)
    await expect(page.getByText("Fix rejected")).toBeVisible()
  })

  test("delivered fix shows View PR link", async ({ page }) => {
    await page.route(/\/api\/v1\/workflow\/(fixes|repositories\/[^/]+\/(fixes|deliveries))/, (route) => {
      route.fulfill({ json: MOCK_FIX_DELIVERED })
    })
    await page.route("**/api/v1/workflow/findings**", (route) => {
      route.fulfill({ json: MOCK_ISSUE_RELIABILITY })
    })

    await page.goto(`/fixes/${MOCK_FIX_DELIVERED.id}`)

    const viewPrLink = page.getByRole("link", { name: "View PR" })
    await expect(viewPrLink).toBeVisible()
    await expect(viewPrLink).toHaveAttribute(
      "href",
      "https://github.com/acme/web-app/pull/42",
    )
  })
})
