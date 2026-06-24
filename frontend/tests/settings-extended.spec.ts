import { expect, test } from "@playwright/test"
import {
  MOCK_AI_PROVIDERS,
  MOCK_INSTALLATION,
  MOCK_ORG,
  MOCK_SUPERUSER,
  MOCK_USER,
  mockAnalyses,
  mockBilling,
  mockEvents,
  mockIssues,
  mockRepositories,
  mockRules,
  mockUserMe,
} from "./utils/mocks"

test.describe("Settings — Integrations tab", () => {
  test.beforeEach(async ({ page }) => {
    await mockEvents(page)
    await mockBilling(page)
    await mockRules(page)
    await mockRepositories(page, [])
    await mockAnalyses(page, [])
    await mockIssues(page, [])
  })

  test("no GitHub linked shows message", async ({ page }) => {
    await mockUserMe(page, { ...MOCK_USER, github_username: null })
    await page.route("**/api/v1/installations/**", (route) => {
      route.fulfill({ json: [] })
    })

    await page.goto("/settings")
    await page.getByRole("tab", { name: "Integrations" }).click()

    await expect(page.getByText("No GitHub account linked")).toBeVisible()
  })

  test("connected GitHub username is visible", async ({ page }) => {
    await mockUserMe(page, { ...MOCK_SUPERUSER, github_username: "octocat" })
    await page.route("**/api/v1/installations/**", (route) => {
      route.fulfill({ json: [] })
    })

    await page.goto("/settings")
    await page.getByRole("tab", { name: "Integrations" }).click()

    await expect(page.getByText("@octocat")).toBeVisible()
  })

  test("organizations list when installations exist", async ({ page }) => {
    await mockUserMe(page, MOCK_SUPERUSER)
    await page.route("**/api/v1/installations/**", (route) => {
      route.fulfill({
        json: [
          MOCK_INSTALLATION,
          {
            ...MOCK_INSTALLATION,
            id: "00000000-0000-0000-0000-000000000011",
            name: "other-org",
          },
        ],
      })
    })

    await page.goto("/settings")
    await page.getByRole("tab", { name: "Integrations" }).click()

    await expect(page.getByText("acme-org")).toBeVisible()
    await expect(page.getByText("other-org")).toBeVisible()
  })

  test("empty state — no installations", async ({ page }) => {
    await mockUserMe(page, MOCK_SUPERUSER)
    await page.route("**/api/v1/installations/**", (route) => {
      route.fulfill({ json: [] })
    })

    await page.goto("/settings")
    await page.getByRole("tab", { name: "Integrations" }).click()

    await expect(page.getByText("No organizations connected")).toBeVisible()
  })
})

test.describe("Settings — AI tab", () => {
  test.beforeEach(async ({ page }) => {
    await mockUserMe(page, MOCK_SUPERUSER)
    await mockEvents(page)
    await mockBilling(page)
    await mockRules(page)
    await mockRepositories(page, [])
    await mockAnalyses(page, [])
    await mockIssues(page, [])
  })

  test("no organizations shows message", async ({ page }) => {
    await page.route("**/api/v1/organizations/**", (route) => {
      route.fulfill({ json: [] })
    })

    await page.goto("/settings")
    await page.getByRole("tab", { name: "AI" }).click()

    await expect(page.getByText("No organizations found")).toBeVisible()
  })

  test("org AI card shows provider selector", async ({ page }) => {
    await page.route("**/api/v1/organizations/**", (route) => {
      const url = route.request().url()
      if (url.includes("/ai-providers")) {
        route.fulfill({ json: MOCK_AI_PROVIDERS })
      } else {
        route.fulfill({ json: [MOCK_ORG] })
      }
    })

    await page.goto("/settings")
    await page.getByRole("tab", { name: "AI" }).click()

    await expect(page.getByText("acme-org")).toBeVisible()
    await expect(page.getByLabel("Provider")).toBeVisible()
    await expect(
      page.getByRole("button", { name: "Save preferences" }),
    ).toBeVisible()
  })

  test("save preferences calls API and shows toast", async ({ page }) => {
    let patchCalled = false
    await page.route("**/api/v1/organizations/**", (route) => {
      const url = route.request().url()
      const method = route.request().method()
      if (url.includes("/ai-providers")) {
        route.fulfill({ json: MOCK_AI_PROVIDERS })
      } else if (method === "PATCH") {
        patchCalled = true
        route.fulfill({ json: MOCK_ORG })
      } else {
        route.fulfill({ json: [MOCK_ORG] })
      }
    })

    await page.goto("/settings")
    await page.getByRole("tab", { name: "AI" }).click()

    await page.getByRole("button", { name: "Save preferences" }).click()

    expect(patchCalled).toBe(true)
    await expect(page.getByText("AI preferences saved")).toBeVisible()
  })
})

test.describe("Settings — Danger zone tab", () => {
  test.beforeEach(async ({ page }) => {
    await mockUserMe(page, MOCK_USER)
    await mockEvents(page)
    await mockBilling(page)
    await mockRules(page)
    await mockRepositories(page, [])
    await mockAnalyses(page, [])
    await mockIssues(page, [])
  })

  test("delete account flow shows confirmation dialog", async ({ page }) => {
    let deleteCalled = false
    await page.route("**/api/v1/users/me", (route) => {
      if (route.request().method() === "DELETE") {
        deleteCalled = true
        route.fulfill({ status: 200, json: {} })
      } else {
        route.fulfill({ json: MOCK_USER })
      }
    })

    await page.goto("/settings")
    await page.getByRole("tab", { name: "Danger zone" }).click()

    await page.getByRole("button", { name: "Delete Account" }).click()

    await expect(page.getByText("Confirmation Required")).toBeVisible()
    await expect(page.getByText("permanently deleted")).toBeVisible()

    await page.getByRole("button", { name: "Delete" }).click()

    expect(deleteCalled).toBe(true)
  })
})
