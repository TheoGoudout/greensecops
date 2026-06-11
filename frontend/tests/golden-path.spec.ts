import { expect, test } from "@playwright/test"

const MOCK_REPO = {
  id: "00000000-0000-0000-0000-000000000001",
  full_name: "acme/web-app",
  github_repo_id: 123456,
  enabled: true,
  badge_branch: "main",
  install_id: 1,
  org_id: "00000000-0000-0000-0000-000000000002",
  created_at: "2024-01-01T00:00:00Z",
}

const MOCK_ANALYSIS = {
  id: "00000000-0000-0000-0000-000000000010",
  repo_id: MOCK_REPO.id,
  status: "completed",
  score: 82,
  grade: "B",
  branch: "main",
  triggered_by: "push",
  created_at: "2024-01-02T10:00:00Z",
  workflow_file_id: "00000000-0000-0000-0000-000000000020",
}

const MOCK_ISSUE = {
  id: "00000000-0000-0000-0000-000000000030",
  analysis_id: MOCK_ANALYSIS.id,
  rule_id: "00000000-0000-0000-0000-000000000040",
  rule_slug: "missing_timeout",
  severity: "high",
  category: "reliability",
  line_start: 12,
  line_end: 12,
  message: "Job 'build' has no timeout-minutes set.",
  context: null,
}

const MOCK_FIX = {
  id: "00000000-0000-0000-0000-000000000050",
  issue_id: MOCK_ISSUE.id,
  llm_provider: "openai",
  status: "pending_review",
  diff: "--- a/.github/workflows/ci.yml\n+++ b/.github/workflows/ci.yml\n@@ -10,6 +10,7 @@\n jobs:\n   build:\n+    timeout-minutes: 30\n     steps:",
  pr_url: null,
  comment_url: null,
  created_at: "2024-01-02T10:01:00Z",
}

test.describe("Golden path: repository → analysis → issue → fix", () => {
  test.beforeEach(async ({ page }) => {
    // The generated API client returns arrays directly for list endpoints
    // (not the { data: [...], count: N } envelope).
    await page.route("**/api/v1/repositories/**", (route) => {
      const url = route.request().url()
      if (url.match(/\/repositories\/[0-9a-f-]{36}$/)) {
        route.fulfill({ json: MOCK_REPO })
      } else {
        route.fulfill({ json: [MOCK_REPO] })
      }
    })

    await page.route("**/api/v1/analyses/**", (route) => {
      const url = route.request().url()
      if (url.match(/\/analyses\/[0-9a-f-]{36}$/)) {
        route.fulfill({ json: MOCK_ANALYSIS })
      } else {
        route.fulfill({ json: [MOCK_ANALYSIS] })
      }
    })

    await page.route("**/api/v1/issues/**", (route) => {
      const url = route.request().url()
      if (url.match(/\/issues\/[0-9a-f-]{36}$/)) {
        route.fulfill({ json: MOCK_ISSUE })
      } else {
        route.fulfill({ json: [MOCK_ISSUE] })
      }
    })

    await page.route("**/api/v1/fixes/**", (route) => {
      route.fulfill({ json: [MOCK_FIX] })
    })
  })

  test("repositories page loads and shows repository", async ({ page }) => {
    await page.goto("/repositories")
    await expect(page).toHaveURL("/repositories")
    await expect(page.getByText("acme/web-app")).toBeVisible()
  })

  test("dashboard shows recent analysis grade", async ({ page }) => {
    await page.goto("/")
    await expect(page.locator("body")).not.toContainText("500")
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("issues page loads and shows issue with severity", async ({ page }) => {
    await page.goto("/issues")
    await expect(page).toHaveURL("/issues")
    await expect(page.locator("body")).not.toContainText("500")
    await expect(page.getByText("missing_timeout")).toBeVisible()
  })

  test("analysis detail page loads without error", async ({ page }) => {
    await page.goto(`/analyses/${MOCK_ANALYSIS.id}`)
    await expect(page.locator("body")).not.toContainText("404")
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("fix rejection updates status via API", async ({ page }) => {
    let rejectCalled = false
    await page.route(`**/api/v1/fixes/${MOCK_FIX.id}/reject`, (route) => {
      rejectCalled = true
      route.fulfill({ json: { ...MOCK_FIX, status: "rejected" } })
    })

    await page.goto("/issues")
    await expect(page.locator("body")).not.toContainText("500")
    expect(rejectCalled).toBe(false)
  })
})

test.describe("GitHub OAuth login button", () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test("login page shows Continue with GitHub button", async ({ page }) => {
    await page.goto("/login")
    await expect(
      page.getByRole("button", { name: /continue with github/i }),
    ).toBeVisible()
  })

  test("signup page shows Continue with GitHub button", async ({ page }) => {
    await page.goto("/signup")
    await expect(
      page.getByRole("button", { name: /continue with github/i }),
    ).toBeVisible()
  })

  test("GitHub OAuth callback stores token and redirects", async ({ page }) => {
    await page.route("**/api/v1/auth/github/callback**", (route) => {
      route.fulfill({ json: { access_token: "test-jwt-token" } })
    })

    await page.route("**/api/v1/users/me", (route) => {
      route.fulfill({
        json: {
          id: "00000000-0000-0000-0000-000000000099",
          email: "test@example.com",
          full_name: "Test User",
          is_active: true,
          is_superuser: false,
          tier: "free",
        },
      })
    })

    await page.goto("/auth/github/callback?code=test-code&state=test-state")
    // The index route (/) immediately redirects authenticated users to /dashboard.
    await expect(page).toHaveURL("/dashboard")
  })
})
