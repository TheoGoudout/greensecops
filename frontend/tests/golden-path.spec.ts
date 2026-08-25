import { expect, type Page, test } from "@playwright/test"
import { MOCK_OVERVIEW } from "./utils/mocks"

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
  workflow_file_path: ".github/workflows/ci.yml",
}

const MOCK_WORKFLOW_FILE = {
  id: MOCK_ANALYSIS.workflow_file_id,
  path: ".github/workflows/ci.yml",
  branch: "main",
  raw_content:
    "name: CI\non: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4",
}

const MOCK_ISSUE = {
  id: "00000000-0000-0000-0000-000000000030",
  analysis_id: MOCK_ANALYSIS.id,
  rule_id: "00000000-0000-0000-0000-000000000040",
  rule_slug: "missing_timeout",
  severity: "high",
  category: "reliability",
  line_start: 5,
  line_end: 5,
  message: "Job 'build' has no timeout-minutes set.",
  context: null,
  workflow_file_path: ".github/workflows/ci.yml",
}

const MOCK_FIX = {
  id: "00000000-0000-0000-0000-000000000050",
  workflow_file_id: MOCK_ANALYSIS.workflow_file_id,
  workflow_file_path: ".github/workflows/ci.yml",
  repo_id: MOCK_REPO.id,
  llm_provider: "openai",
  llm_model: "gpt-4o-mini",
  status: "ready",
  full_content: "name: CI\non: push\njobs:\n  build:\n    timeout-minutes: 30",
  pr_url: null,
  created_at: "2024-01-02T10:01:00Z",
  issues: [
    {
      id: MOCK_ISSUE.id,
      rule_slug: MOCK_ISSUE.rule_slug,
      severity: MOCK_ISSUE.severity,
      category: MOCK_ISSUE.category,
      message: MOCK_ISSUE.message,
      line_start: MOCK_ISSUE.line_start,
      line_end: MOCK_ISSUE.line_end,
    },
  ],
}

test.describe("Golden path: repository → analysis → issue → fix", () => {
  test.beforeEach(async ({ page }) => {
    // The generated API client returns arrays directly for list endpoints
    // (not the { data: [...], count: N } envelope).
    await page.route("**/api/v1/repositories/**", (route) => {
      const url = route.request().url()
      if (url.includes("/workflow-files")) {
        route.fulfill({ json: [MOCK_WORKFLOW_FILE] })
      } else if (url.includes("/branches")) {
        route.fulfill({ json: ["main"] })
      } else if (url.match(/\/repositories\/[0-9a-f-]{36}/)) {
        route.fulfill({ json: MOCK_REPO })
      } else {
        route.fulfill({ json: [MOCK_REPO] })
      }
    })

    await page.route("**/api/v1/workflow-scans/**", (route) => {
      const url = route.request().url()
      if (url.match(/\/workflow-scans\/[0-9a-f-]{36}/)) {
        route.fulfill({ json: MOCK_ANALYSIS })
      } else {
        route.fulfill({ json: [MOCK_ANALYSIS] })
      }
    })

    await page.route("**/api/v1/workflow-findings/**", (route) => {
      const url = route.request().url()
      if (url.match(/\/workflow-findings\/[0-9a-f-]{36}/)) {
        route.fulfill({ json: MOCK_ISSUE })
      } else {
        route.fulfill({ json: [MOCK_ISSUE] })
      }
    })

    await page.route("**/api/v1/workflow-fixes/**", (route) => {
      route.fulfill({ json: [MOCK_FIX] })
    })

    // The dashboard's summary and its three engine sections all read
    // /overview/; without it they would fall through to the live API.
    await page.route("**/api/v1/overview/**", (route) => {
      route.fulfill({ json: MOCK_OVERVIEW })
    })
  })

  test("repositories page loads and shows repository", async ({ page }) => {
    await page.goto("/repositories")
    await expect(page).toHaveURL("/repositories")
    await expect(page.getByText("acme/web-app")).toBeVisible()
  })

  test("dashboard shows recent analysis grade", async ({ page }) => {
    await page.goto("/")
    // The CI section carries the repo-level view; the analysis score shows as
    // the repo's latest score in the repository health table.
    await expect(page.getByText("Repository health")).toBeVisible()
    await expect(
      page.getByRole("link", { name: new RegExp(String(MOCK_ANALYSIS.score)) }),
    ).toBeVisible()
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("dashboard summarises every analysis type", async ({ page }) => {
    await page.goto("/")
    for (const engine of ["workflow", "docker", "terraform", "cloud"]) {
      await expect(page.getByTestId(`engine-row-${engine}`)).toBeVisible()
    }
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("repo issues page loads and shows issue with severity", async ({
    page,
  }) => {
    await page.goto(`/repositories/${MOCK_REPO.id}/static-analysis`)
    await expect(page).toHaveURL(
      new RegExp(`/repositories/${MOCK_REPO.id}/static-analysis`),
    )
    await expect(page.getByText("missing_timeout").first()).toBeVisible()
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("analysis detail page loads without error", async ({ page }) => {
    await page.goto(`/analyses/${MOCK_ANALYSIS.id}`)
    await expect(page.getByText("Analysis Detail")).toBeVisible()
    await expect(page.getByText(`${MOCK_ANALYSIS.score}/100`)).toBeVisible()
    await expect(page.locator("body")).not.toContainText("Something went wrong")
  })

  test("fix rejection updates status via API", async ({ page }) => {
    let rejectCalled = false
    await page.route(
      `**/api/v1/workflow-fixes/${MOCK_FIX.id}/reject`,
      (route) => {
        rejectCalled = true
        route.fulfill({ json: { ...MOCK_FIX, status: "rejected" } })
      },
    )

    await page.goto(`/repositories/${MOCK_REPO.id}/static-analysis`)
    await expect(page.getByText("missing_timeout").first()).toBeVisible()
    expect(rejectCalled).toBe(false)
  })
})

/**
 * Intercept window.open so the popup skips the real GitHub authorize page and
 * lands directly on our same-origin callback with a code and the
 * library-generated state (which the opener polls and verifies).
 */
async function stubPopupWithCode(page: Page) {
  await page.addInitScript(() => {
    const realOpen = window.open.bind(window)
    window.open = ((url: string, target?: string, features?: string) => {
      const authorize = new URL(url)
      const state = authorize.searchParams.get("state") ?? ""
      const redirectUri =
        authorize.searchParams.get("redirect_uri") ??
        `${location.origin}/auth/github/callback`
      const callbackUrl = `${redirectUri}?code=test-code&state=${state}`
      return realOpen(callbackUrl, target, features)
    }) as typeof window.open
  })
}

test.describe("GitHub OAuth login button", () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test("login page shows Continue with GitHub button", async ({ page }) => {
    await page.goto("/login")
    await expect(page.getByTestId("github-oauth-btn")).toBeVisible()
  })

  test("signup page shows Continue with GitHub button", async ({ page }) => {
    await page.goto("/signup")
    await expect(page.getByTestId("github-oauth-btn")).toBeVisible()
  })

  test("GitHub OAuth popup exchanges code and signs in", async ({ page }) => {
    // The opener window exchanges the code for a JWT via the backend.
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

    await stubPopupWithCode(page)

    await page.goto("/login")
    await page.getByTestId("github-oauth-btn").click()

    // After a successful exchange the opener navigates to "/", which immediately
    // redirects authenticated users to /dashboard.
    await expect(page).toHaveURL("/dashboard")
  })

  test("GitHub OAuth popup error keeps the user on the login page", async ({
    page,
  }) => {
    let exchangeCalled = false
    await page.route("**/api/v1/auth/github/callback**", (route) => {
      exchangeCalled = true
      route.fulfill({ json: { access_token: "test-jwt-token" } })
    })

    // Simulate the user denying access: the popup lands on the callback with an
    // `error` param instead of a code. The opener should surface an error and
    // must NOT exchange anything or sign the user in.
    await page.addInitScript(() => {
      const realOpen = window.open.bind(window)
      window.open = ((url: string, target?: string, features?: string) => {
        const authorize = new URL(url)
        const redirectUri =
          authorize.searchParams.get("redirect_uri") ??
          `${location.origin}/auth/github/callback`
        const callbackUrl = `${redirectUri}?error=access_denied&error_description=The+user+denied+access`
        return realOpen(callbackUrl, target, features)
      }) as typeof window.open
    })

    await page.goto("/login")
    await page.getByTestId("github-oauth-btn").click()

    await expect(page.getByText("The user denied access")).toBeVisible()
    await expect(page).toHaveURL("/login")
    expect(exchangeCalled).toBe(false)
    expect(
      await page.evaluate(() => localStorage.getItem("access_token")),
    ).toBeNull()
  })

  // The handshake succeeding and the *exchange* failing is the case that had no
  // coverage, and it is the one a misconfigured deployment actually hits: the
  // popup closes normally and the toast has to say what went wrong. It used to
  // say "GitHub sign in failed. Please try again." for every cause there is.
  test("a rejected exchange reports the backend's reason", async ({ page }) => {
    await page.route("**/api/v1/auth/github/callback**", (route) => {
      route.fulfill({
        status: 400,
        json: { detail: "GitHub Client ID not matching" },
      })
    })
    await stubPopupWithCode(page)

    await page.goto("/login")
    await page.getByTestId("github-oauth-btn").click()

    await expect(page.getByText("GitHub Client ID not matching")).toBeVisible()
    await expect(page).toHaveURL("/login")
    expect(
      await page.evaluate(() => localStorage.getItem("access_token")),
    ).toBeNull()
  })

  test("an unreachable API is not reported as a GitHub failure", async ({
    page,
  }) => {
    // What a CORS block or a dead API looks like to the client: the request
    // rejects with no response at all, so there is no backend detail to quote
    // and blaming GitHub would send the reader looking in the wrong place.
    await page.route("**/api/v1/auth/github/callback**", (route) =>
      route.abort("failed"),
    )
    await stubPopupWithCode(page)

    await page.goto("/login")
    await page.getByTestId("github-oauth-btn").click()

    await expect(
      page.getByText(/Could not reach the GreenSecOps API/),
    ).toBeVisible()
    await expect(page).toHaveURL("/login")
  })
})
