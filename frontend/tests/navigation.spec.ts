import { expect, test } from "@playwright/test"
import {
  MOCK_SUPERUSER,
  MOCK_USER,
  mockAnalyses,
  mockAnsibleProjects,
  mockBilling,
  mockDockerTargets,
  mockEvents,
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
    mockRepositories(page, []),
    mockAnalyses(page, []),
    mockIssues(page, []),
    mockDockerTargets(page, []),
    mockAnsibleProjects(page, []),
  ])
}

test.describe("Navigation", () => {
  test("superuser sees all sidebar links including Admin", async ({ page }) => {
    await mockUserMe(page, MOCK_SUPERUSER)
    await setupAllMocks(page)

    await page.goto("/dashboard")

    for (const label of [
      "Dashboard",
      "Repositories",
      "Docker",
      "Terraform",
      "Rules",
      "Badges",
      "Billing",
    ]) {
      await expect(
        page.locator('[data-sidebar="menu"]').getByText(label, { exact: true }),
      ).toBeVisible()
    }
    await expect(
      page
        .locator('[data-sidebar="menu"]')
        .getByRole("link", { name: "Admin" }),
    ).toBeVisible()
  })

  test("non-superuser does not see Admin link", async ({ page }) => {
    await mockUserMe(page, MOCK_USER)
    await setupAllMocks(page)

    await page.goto("/dashboard")

    await expect(
      page.locator('[data-sidebar="menu"]').getByText("Dashboard"),
    ).toBeVisible()
    await expect(
      page
        .locator('[data-sidebar="menu"]')
        .getByRole("link", { name: "Admin" }),
    ).not.toBeVisible()
  })

  test("sidebar links navigate correctly", async ({ page }) => {
    await mockUserMe(page, MOCK_SUPERUSER)
    await setupAllMocks(page)
    await page.route("**/api/v1/installations/**", (route) => {
      route.fulfill({ json: [] })
    })
    await page.route("**/api/v1/organizations/**", (route) => {
      route.fulfill({ json: [] })
    })
    await page.route("**/api/v1/users/**", (route) => {
      const url = route.request().url()
      if (url.endsWith("/me")) {
        route.fulfill({ json: MOCK_SUPERUSER })
      } else {
        route.fulfill({ json: { data: [MOCK_SUPERUSER], count: 1 } })
      }
    })

    await page.goto("/dashboard")

    const navLinks: Array<[string, RegExp]> = [
      ["Repositories", /\/repositories/],
      ["Docker", /\/docker$/],
      ["Terraform", /\/infrastructure$/],
      // Ansible is its own Infrastructure entry, not a tab under Terraform.
      ["Ansible", /\/infrastructure\/ansible$/],
      ["Rules", /\/rules/],
      // One Badges entry now, with a tab per engine; it lands on the first tab.
      ["Badges", /\/badges\/repositories/],
      ["Billing", /\/billing/],
      ["Dashboard", /\/dashboard/],
    ]

    for (const [label, pattern] of navLinks) {
      await page
        .locator('[data-sidebar="menu"]')
        .getByText(label, { exact: true })
        .click()
      await expect(page).toHaveURL(pattern)
    }
  })

  test("user menu shows Settings and Log out", async ({ page }) => {
    await mockUserMe(page, MOCK_USER)
    await setupAllMocks(page)

    await page.goto("/dashboard")

    await page.getByTestId("user-menu").click()

    await expect(
      page.getByRole("menuitem", { name: /User Settings/i }),
    ).toBeVisible()
    await expect(page.getByRole("menuitem", { name: /Log out/i })).toBeVisible()
  })

  test("page titles are correct", async ({ page }) => {
    // Five full navigations share one test budget, and the first two are the
    // heaviest routes in the app — enough to exhaust it on a cold dev server
    // before the loop reaches /rules. Same reason docker.spec.ts marks its
    // equivalent slow.
    test.slow()
    await mockUserMe(page, MOCK_USER)
    await setupAllMocks(page)

    const pages: Array<[string, string]> = [
      ["/dashboard", "Dashboard - GreenSecOps"],
      // Docker page titles are asserted in docker.spec.ts — this loop shares
      // one test timeout across every goto, so it stays short.
      ["/repositories", "Repositories - GreenSecOps"],
      ["/rules", "Rules - GreenSecOps"],
      ["/badges", "Badges - GreenSecOps"],
      ["/billing", "Billing - GreenSecOps"],
    ]

    for (const [path, expectedTitle] of pages) {
      await page.goto(path)
      await expect(page).toHaveTitle(expectedTitle)
    }
  })
})
