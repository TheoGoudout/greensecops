import { expect, test } from "@playwright/test"
import {
  MOCK_ANALYSIS,
  MOCK_REPO,
  MOCK_SUPERUSER,
  MOCK_USER,
  mockAnalyses,
  mockBilling,
  mockEvents,
  mockFixes,
  mockIssues,
  mockRepositories,
  mockRules,
  mockUserMe,
} from "./utils/mocks"

function setupAllMocks(page: import("@playwright/test").Page) {
  return Promise.all([
    mockEvents(page),
    mockBilling(page),
    mockRules(page),
    mockRepositories(page, [MOCK_REPO]),
    mockAnalyses(page, [MOCK_ANALYSIS]),
    mockIssues(page, []),
    mockFixes(page, []),
  ])
}

test.describe("Navigation — User Menu", () => {
  test("user menu shows logged-in user full name", async ({ page }) => {
    await mockUserMe(page, MOCK_USER)
    await setupAllMocks(page)

    await page.goto("/dashboard")

    await page.getByTestId("user-menu").click()

    await expect(page.getByText("Test User").first()).toBeVisible()
  })

  test("user menu shows logged-in user email", async ({ page }) => {
    await mockUserMe(page, MOCK_USER)
    await setupAllMocks(page)

    await page.goto("/dashboard")

    await page.getByTestId("user-menu").click()

    await expect(page.getByText("user@example.com").first()).toBeVisible()
  })

  test("user menu contains Settings link", async ({ page }) => {
    await mockUserMe(page, MOCK_USER)
    await setupAllMocks(page)

    await page.goto("/dashboard")

    await page.getByTestId("user-menu").click()

    await expect(
      page.getByRole("menuitem", { name: /settings/i }),
    ).toBeVisible()
  })

  test("user menu Settings link navigates to /settings", async ({ page }) => {
    await mockUserMe(page, MOCK_USER)
    await setupAllMocks(page)

    await page.goto("/dashboard")

    await page.getByTestId("user-menu").click()
    await page.getByRole("menuitem", { name: /settings/i }).click()

    await expect(page).toHaveURL(/\/settings/)
  })
})

test.describe("Navigation — Breadcrumbs and Deep Links", () => {
  test("clicking analysis row navigates to analysis detail", async ({
    page,
  }) => {
    await mockUserMe(page, MOCK_SUPERUSER)
    await setupAllMocks(page)

    await page.goto(`/repositories/${MOCK_REPO.id}/analyses`)

    await page.getByText("ci.yml").first().click()

    await expect(page).toHaveURL(new RegExp(`/analyses/${MOCK_ANALYSIS.id}`))
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("analysis detail page links back to repository", async ({ page }) => {
    await mockUserMe(page, MOCK_SUPERUSER)
    await setupAllMocks(page)

    await page.route("**/api/v1/analyses/**", (route) => {
      route.fulfill({ json: MOCK_ANALYSIS })
    })

    await page.goto(`/analyses/${MOCK_ANALYSIS.id}`)

    const repoLink = page.getByRole("link", { name: /acme\/web-app/i })
    if (await repoLink.isVisible()) {
      await repoLink.click()
      await expect(page).toHaveURL(new RegExp(`/repositories/${MOCK_REPO.id}`))
    }
  })

  test("sidebar Repositories link navigates to /repositories", async ({
    page,
  }) => {
    await mockUserMe(page, MOCK_USER)
    await setupAllMocks(page)

    await page.goto("/dashboard")

    await page
      .getByRole("link", { name: /repositories/i })
      .first()
      .click()

    await expect(page).toHaveURL(/\/repositories/)
  })

  test("sidebar Rules link navigates to /rules", async ({ page }) => {
    await mockUserMe(page, MOCK_USER)
    await setupAllMocks(page)

    await page.goto("/dashboard")

    await page.getByRole("link", { name: /rules/i }).first().click()

    await expect(page).toHaveURL(/\/rules/)
  })

  test("sidebar Badges link navigates to /badges", async ({ page }) => {
    await mockUserMe(page, MOCK_USER)
    await setupAllMocks(page)

    await page.goto("/dashboard")

    await page
      .getByRole("link", { name: /badges/i })
      .first()
      .click()

    await expect(page).toHaveURL(/\/badges/)
  })

  test("sidebar Billing link navigates to /billing", async ({ page }) => {
    await mockUserMe(page, MOCK_USER)
    await setupAllMocks(page)

    await page.goto("/dashboard")

    await page
      .getByRole("link", { name: /billing/i })
      .first()
      .click()

    await expect(page).toHaveURL(/\/billing/)
  })
})

test.describe("Navigation — Superuser links", () => {
  test("superuser sees Admin link in sidebar", async ({ page }) => {
    await mockUserMe(page, MOCK_SUPERUSER)
    await setupAllMocks(page)

    await page.goto("/dashboard")

    await expect(
      page.getByRole("link", { name: /admin/i }).first(),
    ).toBeVisible()
  })

  test("regular user does not see Admin link", async ({ page }) => {
    await mockUserMe(page, MOCK_USER)
    await setupAllMocks(page)

    await page.goto("/dashboard")

    await expect(page.getByRole("link", { name: /^admin$/i })).not.toBeVisible()
  })
})
