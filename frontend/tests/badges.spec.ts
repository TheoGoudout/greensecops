import { expect, test } from "@playwright/test"
import {
  MOCK_DOCKER_TARGET,
  MOCK_REPO,
  MOCK_REPO_DISABLED,
  mockAnalyses,
  mockBilling,
  mockDockerTargets,
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
    await page.route("**/api/v1/badges**", (route) => {
      route.fulfill({
        status: 200,
        contentType: "image/svg+xml",
        body: '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="20"><text y="15">B</text></svg>',
      })
    })

    await page.goto("/badges")

    await expect(page.getByRole("heading", { name: "Badges" })).toBeVisible()
    await expect(page.getByText("acme/web-app", { exact: true })).toBeVisible()
    await expect(
      page.getByText("acme/old-service", { exact: true }),
    ).toBeVisible()

    const images = page.locator("img[alt*='GreenSecOps badge']")
    await expect(images).toHaveCount(2)
  })

  test("badge card shows markdown snippet", async ({ page }) => {
    await mockReposRoute(page, [MOCK_REPO])
    await page.route("**/api/v1/badges**", (route) => {
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
    await page.route("**/api/v1/badges**", (route) => {
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

  test("/badges lands on the repositories tab", async ({ page }) => {
    await mockReposRoute(page, [MOCK_REPO])

    await page.goto("/badges")

    await expect(page).toHaveURL(/\/badges\/repositories/)
    await expect(page.getByRole("heading", { name: "Badges" })).toBeVisible()
  })

  test("tabs switch between each engine's badges", async ({ page }) => {
    await mockReposRoute(page, [MOCK_REPO])
    await mockDockerTargets(page)

    await page.goto("/badges")
    // Scoped to the page's tab bar: the sidebar carries its own Docker link.
    const tabs = page.locator("nav.border-b")
    await tabs.getByRole("link", { name: "Docker", exact: true }).click()

    await expect(page).toHaveURL(/\/badges\/docker/)
    await expect(
      page.getByText(`/api/v1/badges/docker/${MOCK_DOCKER_TARGET.id}.svg`),
    ).toBeVisible()
  })

  test("terraform tab shows its own empty state", async ({ page }) => {
    await mockReposRoute(page, [MOCK_REPO])
    await page.route("**/api/v1/terraform/roots**", (route) => {
      route.fulfill({ json: [] })
    })

    await page.goto("/badges/terraform")

    await expect(page.getByText("No Terraform roots found.")).toBeVisible()
  })

  test("the old per-engine badge URLs still resolve", async ({ page }) => {
    // Both lived in the sidebar for a release, so bookmarks and older PR
    // bodies point at them.
    await mockReposRoute(page, [MOCK_REPO])
    await page.route("**/api/v1/terraform/roots**", (route) => {
      route.fulfill({ json: [] })
    })
    await mockDockerTargets(page)

    await page.goto("/infrastructure/badges")
    await expect(page).toHaveURL(/\/badges\/terraform/)

    await page.goto("/docker/badges")
    await expect(page).toHaveURL(/\/badges\/docker/)
  })
})

async function mockReposRoute(
  page: import("@playwright/test").Page,
  repos: unknown[],
) {
  await page.route("**/api/v1/repositories**", (route) => {
    route.fulfill({ json: repos })
  })
}
