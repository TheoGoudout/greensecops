import { expect, test } from "@playwright/test"
import { mockBilling, mockEvents, mockUserMe } from "./utils/mocks"

function setupMinimalMocks(page: import("@playwright/test").Page) {
  return Promise.all([
    mockUserMe(page),
    mockEvents(page),
    mockBilling(page),
    page.route("**/api/v1/repositories**", (route) =>
      route.fulfill({ json: [] }),
    ),
    page.route(/\/api\/v1\/workflow\/(repositories\/[^/]+\/)?scans/, (route) =>
      route.fulfill({ json: [] }),
    ),
    page.route("**/api/v1/workflow/findings**", (route) =>
      route.fulfill({ json: [] }),
    ),
    page.route("**/api/v1/rules**", (route) => route.fulfill({ json: [] })),
  ])
}

test.describe("Auth redirects — authenticated user", () => {
  test("visiting /login redirects away from login page", async ({ page }) => {
    await setupMinimalMocks(page)
    await page.goto("/login")
    await expect(page).not.toHaveURL("/login", { timeout: 5000 })
  })

  test("visiting /signup redirects away from signup page", async ({ page }) => {
    await setupMinimalMocks(page)
    await page.goto("/signup")
    await expect(page).not.toHaveURL("/signup", { timeout: 5000 })
  })

  test("visiting /recover-password redirects away", async ({ page }) => {
    await setupMinimalMocks(page)
    await page.goto("/recover-password")
    await expect(page).not.toHaveURL("/recover-password", { timeout: 5000 })
  })
})

test.describe("Auth redirects — unauthenticated", () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test("login form submitted with empty fields shows validation error", async ({
    page,
  }) => {
    await page.goto("/login")
    await page.getByRole("button", { name: "Log In" }).click()
    await expect(page).toHaveURL("/login")
    await expect(page.locator("body")).toContainText(/required|invalid|enter/i)
  })

  test("accessing /dashboard redirects to /login", async ({ page }) => {
    await page.goto("/dashboard")
    await expect(page).toHaveURL(/\/login/, { timeout: 5000 })
  })

  test("accessing /analyses/:id redirects to /login", async ({ page }) => {
    await page.goto("/analyses/00000000-0000-0000-0000-000000000040")
    await expect(page).toHaveURL(/\/login/, { timeout: 5000 })
  })

  test("accessing /workflows redirects to /login", async ({ page }) => {
    await page.goto("/workflows")
    await expect(page).toHaveURL(/\/login/, { timeout: 5000 })
  })

  test("accessing /admin redirects to /login", async ({ page }) => {
    await page.goto("/admin")
    await expect(page).toHaveURL(/\/login/, { timeout: 5000 })
  })

  test("accessing /settings redirects to /login", async ({ page }) => {
    await page.goto("/settings")
    await expect(page).toHaveURL(/\/login/, { timeout: 5000 })
  })

  test("accessing /billing redirects to /login", async ({ page }) => {
    await page.goto("/billing")
    await expect(page).toHaveURL(/\/login/, { timeout: 5000 })
  })

  test("GitHub App callback when unauthenticated does not crash", async ({
    page,
  }) => {
    await page.goto("/auth/github/app-callback")
    await expect(page).toHaveURL(/\/login|\/auth\/github\/app-callback/, {
      timeout: 5000,
    })
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })
})
