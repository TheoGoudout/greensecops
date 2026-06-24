import { expect, test } from "@playwright/test"
import {
  MOCK_REPO,
  MOCK_REPO_DISABLED,
  mockAnalyses,
  mockBilling,
  mockEvents,
  mockIssues,
  mockRules,
  mockUserMe,
} from "./utils/mocks"

test.describe("Badges", () => {
  test.beforeEach(async ({ page }) => {
    await mockUserMe(page)
    await mockEvents(page)
    await mockBilling(page)
    await mockRules(page)
    await mockAnalyses(page, [])
    await mockIssues(page, [])
  })

  test("shows badge cards for repos", async ({ page }) => {
    await mockReposRoute(page, [MOCK_REPO, MOCK_REPO_DISABLED])
    await page.route("**/api/v1/badges/**", (route) => {
      route.fulfill({
        status: 200,
        contentType: "image/svg+xml",
        body: '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="20"><text y="15">B</text></svg>',
      })
    })

    await page.goto("/badges")

    await expect(page.getByRole("heading", { name: "Badges" })).toBeVisible()
    await expect(
      page.getByText("acme/web-app", { exact: true }),
    ).toBeVisible()
    await expect(
      page.getByText("acme/old-service", { exact: true }),
    ).toBeVisible()

    const images = page.locator("img[alt*='GreenSecOps badge']")
    await expect(images).toHaveCount(2)
  })

  test("badge card shows markdown snippet", async ({ page }) => {
    await mockReposRoute(page, [MOCK_REPO])
    await page.route("**/api/v1/badges/**", (route) => {
      route.fulfill({
        status: 200,
        contentType: "image/svg+xml",
        body: '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="20"><text y="15">B</text></svg>',
      })
    })

    await page.goto("/badges")

    await expect(
      page.locator("code").filter({ hasText: "![GreenSecOps]" }),
    ).toBeVisible()
  })

  test("copy markdown button changes to Copied", async ({ page }) => {
    await mockReposRoute(page, [MOCK_REPO])
    await page.route("**/api/v1/badges/**", (route) => {
      route.fulfill({
        status: 200,
        contentType: "image/svg+xml",
        body: '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="20"><text y="15">B</text></svg>',
      })
    })

    await page.goto("/badges")

    await page.context().grantPermissions(["clipboard-read", "clipboard-write"])

    const copyBtn = page.getByRole("button", { name: "Copy Markdown" })
    await expect(copyBtn).toBeVisible()
    await copyBtn.click()

    await expect(page.getByRole("button", { name: "Copied" })).toBeVisible()
  })

  test("empty state when no repos", async ({ page }) => {
    await mockReposRoute(page, [])

    await page.goto("/badges")

    await expect(page.getByText("No repositories found.")).toBeVisible()
  })
})

async function mockReposRoute(
  page: import("@playwright/test").Page,
  repos: unknown[],
) {
  await page.route("**/api/v1/repositories/**", (route) => {
    route.fulfill({ json: repos })
  })
}
