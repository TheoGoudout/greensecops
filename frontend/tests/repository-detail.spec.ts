import { expect, test } from "@playwright/test"
import {
  MOCK_ANALYSIS,
  MOCK_FIX_DELIVERED,
  MOCK_FIX_READY,
  MOCK_ISSUE_ENERGY,
  MOCK_ISSUE_RELIABILITY,
  MOCK_ISSUE_SECURITY,
  MOCK_ISSUE_WITH_FIX,
  MOCK_PR_OPEN,
  MOCK_REPO,
  MOCK_REPO_PRIVATE,
  MOCK_WORKFLOW_FILE,
  mockBilling,
  mockEvents,
  mockRules,
  mockUserMe,
} from "./utils/mocks"

test.describe("Repository Detail", () => {
  test.beforeEach(async ({ page }) => {
    await mockUserMe(page)
    await mockEvents(page)
    await mockBilling(page)
    await mockRules(page)
  })

  function setupRepoMocks(
    page: import("@playwright/test").Page,
    opts: {
      repo?: typeof MOCK_REPO
      analyses?: unknown[]
      findings?: unknown[]
      fixes?: unknown[]
      workflowFiles?: unknown[]
      pullRequests?: unknown[]
    } = {},
  ) {
    const {
      repo = MOCK_REPO,
      analyses = [MOCK_ANALYSIS],
      findings = [
        MOCK_ISSUE_SECURITY,
        MOCK_ISSUE_RELIABILITY,
        MOCK_ISSUE_ENERGY,
      ],
      fixes = [],
      workflowFiles = [MOCK_WORKFLOW_FILE],
      pullRequests = [],
    } = opts

    return Promise.all([
      page.route(/\/api\/v1\/(workflow\/)?repositories\b/, (route) => {
        const url = route.request().url()
        if (url.includes("/workflow-sync")) {
          route.fulfill({
            json: {
              branch: "main",
              head_sha: "abc1234def5678901234567890abcdef12345678",
              added: 1,
              updated: 2,
              unchanged: 3,
              restored: 0,
              deleted: 1,
              skipped_stale: 0,
            },
          })
        } else if (url.includes("/files")) {
          route.fulfill({ json: workflowFiles })
        } else if (url.includes("/action-integration")) {
          route.fulfill({
            json: { pr_url: "https://github.com/acme/web-app/pull/99" },
          })
        } else if (url.includes("/branches")) {
          route.fulfill({ json: ["main"] })
        } else if (url.match(/\/repositories\/[0-9a-f-]{36}$/)) {
          route.fulfill({ json: repo })
        } else {
          route.fulfill({ json: [repo] })
        }
      }),
      page.route(
        /\/api\/v1\/workflow\/(repositories\/[^/]+\/)?scans/,
        (route) => {
          const url = route.request().url()
          const method = route.request().method()
          if (method === "POST" && url.includes("/repositories/")) {
            route.fulfill({
              status: 202,
              json: { status: "queued", repo_id: MOCK_REPO.id },
            })
          } else if (url.match(/\/scans\/[0-9a-f-]{36}$/)) {
            route.fulfill({ json: analyses[0] })
          } else {
            route.fulfill({ json: analyses })
          }
        },
      ),
      page.route("**/api/v1/workflow/findings**", (route) => {
        route.fulfill({ json: findings })
      }),
      page.route(
        /\/api\/v1\/workflow\/(fixes|repositories\/[^/]+\/(fixes|deliveries|pull-requests))/,
        (route) => {
          const url = route.request().url()
          const method = route.request().method()
          if (method === "POST" && url.includes("/pull-requests/sync")) {
            route.fulfill({ json: { synced: 0, updated: 0, relinked: 0 } })
          } else if (
            method === "POST" &&
            new URL(url).pathname.endsWith("/fixes")
          ) {
            route.fulfill({
              status: 202,
              json: { queued: findings.length, skipped: 0 },
            })
          } else if (method === "POST" && url.includes("/deliveries")) {
            route.fulfill({ json: { status: "delivering" } })
          } else if (url.includes("/pull-requests")) {
            route.fulfill({ json: pullRequests })
          } else if (url.match(/\/fixes\/[0-9a-f-]{36}$/)) {
            const id = url.split("/").pop()
            const fix = fixes.find((f: any) => f.id === id) ?? fixes[0]
            route.fulfill({ json: fix })
          } else {
            route.fulfill({ json: fixes })
          }
        },
      ),
    ])
  }

  test("header shows repo name, grade, and default branch", async ({
    page,
  }) => {
    await setupRepoMocks(page)

    await page.goto(`/workflows/${MOCK_REPO.id}`)

    await expect(page.getByText("acme/web-app")).toBeVisible()
    await expect(
      page.getByRole("combobox").filter({ hasText: "main" }),
    ).toBeVisible()
  })

  test("header shows lock icon for private repos", async ({ page }) => {
    await setupRepoMocks(page, { repo: MOCK_REPO_PRIVATE })

    await page.goto(`/workflows/${MOCK_REPO_PRIVATE.id}`)

    await expect(page.getByText("acme/secret-service")).toBeVisible()
    await expect(
      page.locator('[aria-label="Private repository"]'),
    ).toBeVisible()
  })

  test("header hides lock icon for public repos", async ({ page }) => {
    await setupRepoMocks(page)

    await page.goto(`/workflows/${MOCK_REPO.id}`)

    await expect(page.getByText("acme/web-app")).toBeVisible()
    await expect(page.locator('[aria-label="Private repository"]')).toHaveCount(
      0,
    )
  })

  test("Static analysis tab shows workflow card with status", async ({
    page,
  }) => {
    await setupRepoMocks(page)

    await page.goto(`/workflows/${MOCK_REPO.id}`)

    // Default route redirects to the merged Static analysis tab.
    await expect(page).toHaveURL(new RegExp(`/${MOCK_REPO.id}/static-analysis`))
    await expect(page.getByText("ci.yml").first()).toBeVisible()
    await expect(page.getByText("completed").first()).toBeVisible()
  })

  test("Static analysis shows issues inside the workflow card", async ({
    page,
  }) => {
    await setupRepoMocks(page)

    await page.goto(`/workflows/${MOCK_REPO.id}/static-analysis`)

    await expect(
      page
        .getByText("Workflow uses overly permissive token permissions.")
        .first(),
    ).toBeVisible()
  })

  test("Static analysis empty state when no workflow files", async ({
    page,
  }) => {
    await setupRepoMocks(page, { workflowFiles: [] })

    await page.goto(`/workflows/${MOCK_REPO.id}/static-analysis`)

    await expect(page.getByText("No workflow files found")).toBeVisible()
  })

  test("Analysis history section lists analyses", async ({ page }) => {
    await setupRepoMocks(page)

    await page.goto(`/workflows/${MOCK_REPO.id}/static-analysis`)

    await page.getByRole("button", { name: /Analysis history/ }).click()
    await expect(page.getByText("manual")).toBeVisible()
  })

  test("Fix selected button queues fixes", async ({ page }) => {
    const findings = [MOCK_ISSUE_SECURITY, MOCK_ISSUE_RELIABILITY]
    await setupRepoMocks(page, { findings })

    await page.goto(`/workflows/${MOCK_REPO.id}/static-analysis`)

    const fixBtn = page.getByRole("button", { name: /Fix selected/ })
    await expect(fixBtn).toBeVisible()
    await fixBtn.click()

    await expect(page.getByText(/Queued 2 fix/)).toBeVisible()
  })

  test("Static analysis shows fix status and View PR in the card", async ({
    page,
  }) => {
    await setupRepoMocks(page, {
      findings: [MOCK_ISSUE_WITH_FIX],
      fixes: [MOCK_FIX_READY],
    })

    await page.goto(`/workflows/${MOCK_REPO.id}/static-analysis`)

    await expect(page.getByText("ready").first()).toBeVisible()
  })

  test("Create PR for all workflows button delivers repo-wide", async ({
    page,
  }) => {
    let deliverCalled = false
    await page.route(/\/api\/v1\/(workflow\/)?repositories\b/, (route) => {
      const url = route.request().url()
      if (url.includes("/pull-requests")) {
        route.fulfill({ json: [] })
      } else if (url.includes("/files")) {
        route.fulfill({ json: [MOCK_WORKFLOW_FILE] })
      } else if (url.includes("/branches")) {
        route.fulfill({ json: ["main"] })
      } else {
        route.fulfill({ json: MOCK_REPO })
      }
    })
    await page.route(
      /\/api\/v1\/workflow\/(repositories\/[^/]+\/)?scans/,
      (route) => {
        route.fulfill({ json: [MOCK_ANALYSIS] })
      },
    )
    await page.route("**/api/v1/workflow/findings**", (route) => {
      route.fulfill({ json: [MOCK_ISSUE_WITH_FIX] })
    })
    await page.route(
      /\/api\/v1\/workflow\/(fixes|repositories\/[^/]+\/(fixes|deliveries|pull-requests))/,
      (route) => {
        const url = route.request().url()
        const method = route.request().method()
        if (
          method === "POST" &&
          url.includes("/repositories/") &&
          new URL(url).pathname.endsWith("/deliveries")
        ) {
          deliverCalled = true
          route.fulfill({ json: { status: "delivering" } })
        } else if (url.includes("/pull-requests")) {
          route.fulfill({ json: [] })
        } else {
          route.fulfill({ json: [MOCK_FIX_READY] })
        }
      },
    )

    await page.goto(`/workflows/${MOCK_REPO.id}/static-analysis`)

    const btn = page.getByRole("button", {
      name: "Create PR for all workflows",
    })
    await expect(btn).toBeVisible()
    await btn.click()

    expect(deliverCalled).toBe(true)
    await expect(page.getByText("Repo-wide PR queued")).toBeVisible()
  })

  test("PRs tab shows pull requests", async ({ page }) => {
    await setupRepoMocks(page, {
      fixes: [MOCK_FIX_DELIVERED],
      pullRequests: [MOCK_PR_OPEN],
    })

    await page.goto(`/workflows/${MOCK_REPO.id}/pull-requests`)

    await expect(page.getByText("acme/web-app/pull/42")).toBeVisible()
    await expect(page.getByText("open").first()).toBeVisible()
  })

  test("PRs tab lists only the workflow engine's PRs", async ({ page }) => {
    // The PR list endpoint is repo-wide — every engine's tab reads the same
    // rows — so this tab has to narrow to its own branches. It did not, and
    // Terraform, Docker and Ansible fix PRs showed up here with no workflow
    // name and no working Update button.
    await setupRepoMocks(page, {
      fixes: [MOCK_FIX_DELIVERED],
      pullRequests: [
        MOCK_PR_OPEN,
        {
          ...MOCK_PR_OPEN,
          id: "00000000-0000-0000-0000-000000000091",
          pr_branch: "greensecops/terraform-00000000",
          pr_url: "https://github.com/acme/web-app/pull/43",
        },
        {
          ...MOCK_PR_OPEN,
          id: "00000000-0000-0000-0000-000000000092",
          pr_branch: "greensecops/docker-00000000",
          pr_url: "https://github.com/acme/web-app/pull/44",
        },
        {
          ...MOCK_PR_OPEN,
          id: "00000000-0000-0000-0000-000000000093",
          pr_branch: "greensecops/ansible-00000000",
          pr_url: "https://github.com/acme/web-app/pull/45",
        },
      ],
    })

    await page.goto(`/workflows/${MOCK_REPO.id}/pull-requests`)

    await expect(page.getByText("acme/web-app/pull/42")).toBeVisible()
    await expect(page.getByText("acme/web-app/pull/43")).toHaveCount(0)
    await expect(page.getByText("acme/web-app/pull/44")).toHaveCount(0)
    await expect(page.getByText("acme/web-app/pull/45")).toHaveCount(0)
  })

  test("PRs tab keeps the repo-wide and integrate-action branches", async ({
    page,
  }) => {
    // The workflow engine owns three branch shapes, not one prefix: the
    // per-file fix branch, the repo-wide batch branch, and the fixed
    // "Integrate action" branch. Narrowing this tab must keep all three.
    await setupRepoMocks(page, {
      fixes: [],
      pullRequests: [
        {
          ...MOCK_PR_OPEN,
          id: "00000000-0000-0000-0000-000000000094",
          pr_branch: `greensecops/fixes-${MOCK_REPO.id.slice(0, 8)}`,
          pr_url: "https://github.com/acme/web-app/pull/46",
        },
        {
          ...MOCK_PR_OPEN,
          id: "00000000-0000-0000-0000-000000000095",
          pr_branch: "greensecops/integrate-action",
          pr_url: "https://github.com/acme/web-app/pull/47",
        },
      ],
    })

    await page.goto(`/workflows/${MOCK_REPO.id}/pull-requests`)

    await expect(page.getByText("All workflows")).toBeVisible()
    await expect(page.getByText("Integrate action")).toBeVisible()
  })

  test("PRs tab empty state", async ({ page }) => {
    await setupRepoMocks(page, { fixes: [], pullRequests: [] })

    await page.goto(`/workflows/${MOCK_REPO.id}/pull-requests`)

    await expect(
      page.getByText("No GreenSecOps-created PRs yet."),
    ).toBeVisible()
  })

  test("Run analysis button triggers analysis", async ({ page }) => {
    await setupRepoMocks(page)

    await page.goto(`/workflows/${MOCK_REPO.id}`)

    await page.getByRole("button", { name: "Run analysis" }).click()

    await expect(page.getByText("Analysis queued")).toBeVisible()
  })

  test("Sync from GitHub reports what changed", async ({ page }) => {
    await setupRepoMocks(page)

    await page.goto(`/workflows/${MOCK_REPO.id}`)

    await page.getByRole("button", { name: "Sync from GitHub" }).click()

    // The toast summarises the reconciliation rather than just saying "done".
    await expect(
      page.getByText("Synced: 1 added, 2 updated, 1 removed"),
    ).toBeVisible()
  })

  test("workflow card shows which commit the stored copy came from", async ({
    page,
  }) => {
    await setupRepoMocks(page)

    await page.goto(`/workflows/${MOCK_REPO.id}`)

    await expect(page.getByText(/Synced at abc1234/)).toBeVisible()
  })

  test("Integrate action button triggers PR", async ({ page }) => {
    await setupRepoMocks(page)
    // Integrate action lives on the Telemetry tab now.
    await page.route("**/api/v1/telemetry**", (route) => {
      route.fulfill({ json: { runs: [], average: null } })
    })

    await page.goto(`/workflows/${MOCK_REPO.id}/telemetry`)

    await page.getByRole("button", { name: "Integrate action" }).click()

    await expect(page.getByText("PR opened").first()).toBeVisible()
  })

  test("an open integration PR is linked instead of offered again", async ({
    page,
  }) => {
    // The route records a PullRequest row now, so the tab can see the PR it
    // opened. Before, the button only knew within the session that pressed it
    // — after a reload it offered to open a PR that already existed, and
    // pressing it just returned "already present".
    await setupRepoMocks(page, {
      pullRequests: [
        {
          ...MOCK_PR_OPEN,
          pr_branch: "greensecops/integrate-action",
          pr_url: "https://github.com/acme/web-app/pull/99",
        },
      ],
    })
    await page.route("**/api/v1/telemetry**", (route) => {
      route.fulfill({ json: { runs: [], average: null } })
    })

    await page.goto(`/workflows/${MOCK_REPO.id}/telemetry`)

    const link = page.getByRole("link", { name: /View integration PR/ })
    await expect(link).toBeVisible()
    await expect(link).toHaveAttribute(
      "href",
      "https://github.com/acme/web-app/pull/99",
    )
    await expect(
      page.getByRole("button", { name: "Integrate action" }),
    ).toHaveCount(0)
  })

  test("a merged integration PR does not hide the button", async ({ page }) => {
    // Merged means the action is already in the workflows, so the row is
    // history rather than something to link to. Pinning this because matching
    // on the branch alone would leave the link pointing at a stale PR forever.
    await setupRepoMocks(page, {
      pullRequests: [
        {
          ...MOCK_PR_OPEN,
          pr_branch: "greensecops/integrate-action",
          pr_state: "merged" as const,
        },
      ],
    })
    await page.route("**/api/v1/telemetry**", (route) => {
      route.fulfill({ json: { runs: [], average: null } })
    })

    await page.goto(`/workflows/${MOCK_REPO.id}/telemetry`)

    await expect(
      page.getByRole("button", { name: "Integrate action" }),
    ).toBeVisible()
    await expect(
      page.getByRole("link", { name: /View integration PR/ }),
    ).toHaveCount(0)
  })
})
