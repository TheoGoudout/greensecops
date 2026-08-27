import { expect, test } from "@playwright/test"
import {
  buildOverview,
  MOCK_ANALYSIS,
  MOCK_ISSUE_ENERGY,
  MOCK_ISSUE_RELIABILITY,
  MOCK_ISSUE_SECURITY,
  MOCK_OVERVIEW,
  MOCK_REPO,
  MOCK_REPO_DISABLED,
  MOCK_REPO_NO_ANALYSES,
  mockAnalyses,
  mockBilling,
  mockEvents,
  mockIssues,
  mockOverview,
  mockRepositories,
  mockRules,
  mockUserMe,
} from "./utils/mocks"

test.describe("Dashboard", () => {
  test.beforeEach(async ({ page }) => {
    await mockUserMe(page)
    await mockEvents(page)
    await mockBilling(page)
    await mockRules(page)
    // Every test needs /overview/ stubbed — it backs the whole top section and
    // all three collapsible sections. Individual tests re-stub it when they
    // care about the numbers.
    await mockOverview(page)
  })

  // ─── All-analysis-types summary ────────────────────────────────────────────

  test("summary stat cards cover every engine, not just CI", async ({
    page,
  }) => {
    await mockRepositories(page, [MOCK_REPO, MOCK_REPO_DISABLED])
    await mockAnalyses(page, [MOCK_ANALYSIS])
    await mockIssues(page, [])

    await page.goto("/dashboard")

    await expect(page.getByText("Overall score")).toBeVisible()
    await expect(page.getByText("Open findings").first()).toBeVisible()
    await expect(page.getByText("Fix rate")).toBeVisible()
    await expect(page.getByText("Scan coverage")).toBeVisible()

    // MOCK_OVERVIEW: 3 CI + 2 docker + 0 terraform + 1 cloud open findings.
    await expect(page.getByText("2 critical, all engines")).toBeVisible()
  })

  test("the analysis types table lists all four engines", async ({ page }) => {
    await mockRepositories(page, [MOCK_REPO])
    await mockAnalyses(page, [MOCK_ANALYSIS])
    await mockIssues(page, [])

    await page.goto("/dashboard")

    await expect(page.getByText("Analysis types")).toBeVisible()
    for (const engine of ["workflow", "docker", "terraform", "cloud"]) {
      await expect(page.getByTestId(`engine-row-${engine}`)).toBeVisible()
    }
  })

  test("an engine row links to that engine's page", async ({ page }) => {
    await mockRepositories(page, [MOCK_REPO])
    await mockAnalyses(page, [MOCK_ANALYSIS])
    await mockIssues(page, [])

    await page.goto("/dashboard")
    await page.getByTestId("engine-row-docker").click()

    await expect(page).toHaveURL(/\/docker/)
  })

  test("the findings heatmap shows a cell per category per engine", async ({
    page,
  }) => {
    await mockRepositories(page, [MOCK_REPO])
    await mockAnalyses(page, [MOCK_ANALYSIS])
    await mockIssues(page, [])

    await page.goto("/dashboard")

    await expect(page.getByText("Where the findings are")).toBeVisible()
    for (const label of [
      "Energy",
      "Reliability",
      "Security",
      "Performance",
      "Maintainability",
    ]) {
      await expect(page.getByText(label, { exact: true }).first()).toBeVisible()
    }
    // The fixture puts every open finding on "security", so that cell carries
    // CI's 3 and the number is readable without hovering.
    await expect(
      page.getByTitle("3 open security findings — CI workflows"),
    ).toBeVisible()
  })

  test("the heatmap says so when nothing is open anywhere", async ({
    page,
  }) => {
    await mockOverview(page, buildOverview())
    await mockRepositories(page, [])
    await mockAnalyses(page, [])
    await mockIssues(page, [])

    await page.goto("/dashboard")

    await expect(
      page.getByText("No open findings on any engine — nothing to plot yet."),
    ).toBeVisible()
  })

  // ─── Collapsible per-type sections ─────────────────────────────────────────

  test("all three sections render, open by default", async ({ page }) => {
    await mockRepositories(page, [MOCK_REPO])
    await mockAnalyses(page, [MOCK_ANALYSIS])
    await mockIssues(page, [])

    await page.goto("/dashboard")

    for (const section of ["ci", "docker", "infra"]) {
      const card = page.getByTestId(`section-${section}`)
      await expect(card).toBeVisible()
      await expect(card.getByRole("button").first()).toHaveAttribute(
        "aria-expanded",
        "true",
      )
    }
  })

  test("collapsing a section hides its body but keeps its summary", async ({
    page,
  }) => {
    await mockRepositories(page, [MOCK_REPO])
    await mockAnalyses(page, [MOCK_ANALYSIS])
    await mockIssues(page, [])

    await page.goto("/dashboard")

    const docker = page.getByTestId("section-docker")
    const toggle = docker.getByRole("button").first()
    await expect(docker.getByText("Most common findings")).toBeVisible()

    await toggle.click()

    await expect(toggle).toHaveAttribute("aria-expanded", "false")
    await expect(docker.getByText("Most common findings")).not.toBeVisible()
    // A folded section must still answer "is anything wrong in here".
    // MOCK_OVERVIEW gives Docker 2 open findings.
    await expect(docker.getByText("2 open")).toBeVisible()
  })

  test("collapsed sections survive a reload", async ({ page }) => {
    await mockRepositories(page, [MOCK_REPO])
    await mockAnalyses(page, [MOCK_ANALYSIS])
    await mockIssues(page, [])

    await page.goto("/dashboard")
    await page.getByTestId("section-docker").getByRole("button").first().click()
    // Don't wait for `load`: the app holds an SSE stream open for the lifetime
    // of the page, so that event may never fire. The assertions below auto-wait
    // for the re-rendered section anyway.
    await page.reload({ waitUntil: "commit" })

    await expect(
      page.getByTestId("section-docker").getByRole("button").first(),
    ).toHaveAttribute("aria-expanded", "false")
    // Other sections are unaffected.
    await expect(
      page.getByTestId("section-ci").getByRole("button").first(),
    ).toHaveAttribute("aria-expanded", "true")
  })

  test("the infrastructure section covers Terraform and cloud posture", async ({
    page,
  }) => {
    await mockRepositories(page, [MOCK_REPO])
    await mockAnalyses(page, [MOCK_ANALYSIS])
    await mockIssues(page, [])

    await page.goto("/dashboard")

    const infra = page.getByTestId("section-infra")
    // Both engines get their own sub-heading inside the shared section.
    await expect(
      infra.getByRole("heading", { name: "Terraform" }),
    ).toBeVisible()
    await expect(
      infra.getByRole("heading", { name: "Cloud posture" }),
    ).toBeVisible()
  })

  test("cloud posture shows resolved findings, not a fix rate", async ({
    page,
  }) => {
    await mockRepositories(page, [MOCK_REPO])
    await mockAnalyses(page, [MOCK_ANALYSIS])
    await mockIssues(page, [])

    await page.goto("/dashboard")

    // Cloud findings have no fix pipeline, so the card that would show a fix
    // rate is replaced rather than zeroed.
    await expect(
      page.getByText("cloud posture has no fix pipeline"),
    ).toBeVisible()
    await expect(
      page.getByTestId("section-docker").getByText("Being fixed"),
    ).toBeVisible()
  })

  test("an engine with no targets reports nothing scanned", async ({
    page,
  }) => {
    await mockOverview(
      page,
      buildOverview({ workflow: { open: 1, total: 1, scanned: 1 } }),
    )
    await mockRepositories(page, [MOCK_REPO])
    await mockAnalyses(page, [MOCK_ANALYSIS])
    await mockIssues(page, [])

    await page.goto("/dashboard")

    const docker = page.getByTestId("section-docker")
    await expect(docker.getByText("0/0")).toBeVisible()
    await expect(docker.getByText("Nothing scanned yet.")).toBeVisible()
  })

  test("a failed latest scan is called out without losing the grade", async ({
    page,
  }) => {
    const overview = buildOverview({
      docker: { open: 1, total: 2, scanned: 1, score: 72, grade: "B" },
    })
    const docker = overview.engines.find((e) => e.engine === "docker")!
    docker.coverage.latest_scan_failed = 1

    await mockOverview(page, overview)
    await mockRepositories(page, [MOCK_REPO])
    await mockAnalyses(page, [MOCK_ANALYSIS])
    await mockIssues(page, [])

    await page.goto("/dashboard")

    await expect(
      page.getByText(/most recent scan failed/).first(),
    ).toBeVisible()
  })

  // ─── CI section: repo-level widgets ────────────────────────────────────────

  test("repository health table shows repo name, grade, and score", async ({
    page,
  }) => {
    await mockRepositories(page, [MOCK_REPO])
    await mockAnalyses(page, [MOCK_ANALYSIS])
    await mockIssues(page, [])

    await page.goto("/dashboard")

    await expect(page.getByText("Repository health")).toBeVisible()
    await expect(
      page.getByRole("link", { name: /acme\/web-app/ }),
    ).toBeVisible()
  })

  test("empty state when no analyses", async ({ page }) => {
    await mockRepositories(page, [MOCK_REPO])
    await mockAnalyses(page, [])
    await mockIssues(page, [])

    await page.goto("/dashboard")

    await expect(page.getByText("No completed analyses yet.")).toBeVisible()
  })

  test("clicking repository health row navigates to repo analyses", async ({
    page,
  }) => {
    await mockRepositories(page, [MOCK_REPO])
    await mockAnalyses(page, [MOCK_ANALYSIS])
    await mockIssues(page, [])

    await page.goto("/dashboard")

    await page.getByRole("link", { name: /acme\/web-app/ }).click()

    await expect(page).toHaveURL(
      new RegExp(`/repositories/${MOCK_REPO.id}/static-analysis`),
    )
  })

  test("repository health table paginates past 8 repos", async ({ page }) => {
    const repos = []
    const analyses = []
    for (let i = 0; i < 10; i++) {
      const id = `00000000-0000-0000-0000-00000000030${i}`
      repos.push({ ...MOCK_REPO, id, full_name: `acme/service-${i}` })
      analyses.push({ ...MOCK_ANALYSIS, id: `${id}a`, repo_id: id })
    }

    await mockRepositories(page, repos)
    await mockAnalyses(page, analyses)
    await mockIssues(page, [])

    await page.goto("/dashboard")

    const healthCard = page.getByText("Repository health").locator("../..")
    await expect(healthCard.getByText("acme/service-0")).toBeVisible()
    await expect(healthCard.getByText("acme/service-8")).not.toBeVisible()
    await expect(healthCard.getByText("Showing 1-8 of 10")).toBeVisible()

    await healthCard.getByRole("button", { name: "Go to next page" }).click()

    await expect(healthCard.getByText("acme/service-0")).not.toBeVisible()
    await expect(healthCard.getByText("acme/service-8")).toBeVisible()
  })

  test("category health renders a star diagram axis per category", async ({
    page,
  }) => {
    await mockRepositories(page, [MOCK_REPO])
    await mockAnalyses(page, [MOCK_ANALYSIS])
    await mockIssues(page, [
      MOCK_ISSUE_SECURITY,
      MOCK_ISSUE_RELIABILITY,
      MOCK_ISSUE_ENERGY,
    ])

    await page.goto("/dashboard")

    await expect(page.getByText("Category health by repository")).toBeVisible()
    const radar = page.getByRole("img", {
      name: "Category health by repository",
    })
    await expect(radar).toBeVisible()
    for (const label of [
      "Energy",
      "Reliability",
      "Security",
      "Performance",
      "Maintainability",
    ]) {
      await expect(radar.getByText(label)).toBeVisible()
    }
  })

  test("category health excludes repos with no workflows (grade N/A)", async ({
    page,
  }) => {
    // listRepositories returns the literal string "N/A" (never null) for a
    // repo with no CI workflows at all — MOCK_REPO_NO_ANALYSES predates that
    // and stubs grade: null, so build the real shape here.
    const repoNoWorkflows = {
      ...MOCK_REPO_NO_ANALYSES,
      grade: "N/A" as const,
    }

    await mockRepositories(page, [MOCK_REPO, repoNoWorkflows])
    await mockAnalyses(page, [MOCK_ANALYSIS])
    await mockIssues(page, [MOCK_ISSUE_SECURITY])

    await page.goto("/dashboard")

    const legend = page.getByTestId("category-health-legend")
    await expect(legend.getByText(MOCK_REPO.full_name)).toBeVisible()
    await expect(legend.getByText(repoNoWorkflows.full_name)).not.toBeAttached()
    await expect(
      page.locator(`path[data-series-id="${repoNoWorkflows.id}"]`),
    ).not.toBeAttached()
  })

  test("toggling a repo checkbox shows/hides its polygon", async ({ page }) => {
    const repoB = {
      ...MOCK_REPO,
      id: "00000000-0000-0000-0000-000000000200",
      full_name: "acme/api-service",
    }
    const analysisB = {
      ...MOCK_ANALYSIS,
      id: "00000000-0000-0000-0000-000000000201",
      repo_id: repoB.id,
    }
    const issueB = {
      ...MOCK_ISSUE_ENERGY,
      id: "00000000-0000-0000-0000-000000000202",
      scan_id: analysisB.id,
    }

    await mockRepositories(page, [MOCK_REPO, repoB])
    await mockAnalyses(page, [MOCK_ANALYSIS, analysisB])
    await mockIssues(
      page,
      [MOCK_ISSUE_SECURITY, issueB],
      [MOCK_ANALYSIS, analysisB],
    )

    await page.goto("/dashboard")

    const polygonA = page.locator(`path[data-series-id="${MOCK_REPO.id}"]`)
    const polygonB = page.locator(`path[data-series-id="${repoB.id}"]`)
    await expect(polygonA).toBeAttached()
    await expect(polygonB).toBeAttached()

    await page.getByLabel(MOCK_REPO.full_name).uncheck()

    await expect(polygonA).not.toBeAttached()
    await expect(polygonB).toBeAttached()
  })

  test("hovering a repo name dims other repos in the star diagram", async ({
    page,
  }) => {
    const repoB = {
      ...MOCK_REPO,
      id: "00000000-0000-0000-0000-000000000200",
      full_name: "acme/api-service",
    }
    const analysisB = {
      ...MOCK_ANALYSIS,
      id: "00000000-0000-0000-0000-000000000201",
      repo_id: repoB.id,
    }
    const issueB = {
      ...MOCK_ISSUE_ENERGY,
      id: "00000000-0000-0000-0000-000000000202",
      scan_id: analysisB.id,
    }

    await mockRepositories(page, [MOCK_REPO, repoB])
    await mockAnalyses(page, [MOCK_ANALYSIS, analysisB])
    await mockIssues(
      page,
      [MOCK_ISSUE_SECURITY, issueB],
      [MOCK_ANALYSIS, analysisB],
    )

    await page.goto("/dashboard")

    const polygonA = page.locator(`path[data-series-id="${MOCK_REPO.id}"]`)
    const polygonB = page.locator(`path[data-series-id="${repoB.id}"]`)
    const legend = page.getByTestId("category-health-legend")

    await legend.getByText(repoB.full_name).hover()

    await expect
      .poll(() => polygonA.evaluate((el) => getComputedStyle(el).opacity))
      .toBe("0.15")
    await expect
      .poll(() => polygonB.evaluate((el) => getComputedStyle(el).opacity))
      .toBe("1")
  })

  // ─── Chrome ────────────────────────────────────────────────────────────────

  test("/ redirects to /dashboard", async ({ page }) => {
    await mockRepositories(page, [])
    await mockAnalyses(page, [])
    await mockIssues(page, [])

    await page.goto("/")

    await expect(page).toHaveURL(/\/dashboard/)
  })

  test("loading skeletons appear while data loads", async ({ page }) => {
    await mockRepositories(page, [MOCK_REPO])
    await mockAnalyses(page, [MOCK_ANALYSIS])
    await mockIssues(page, [])
    // Delay /overview/, not /analyses/: it backs the summary cards and gates
    // every section, so it is what governs the dashboard's first paint.
    // Registered after the beforeEach stub, so it wins the route match.
    await page.route("**/api/v1/overview**", async (route) => {
      await new Promise((r) => setTimeout(r, 3000))
      route.fulfill({ json: MOCK_OVERVIEW })
    })

    // `waitUntil: "commit"` so goto returns before the delayed request
    // settles — the default waits for `load`, which the in-flight XHR holds
    // open, so the loading state is already gone by the time it resolves.
    await page.goto("/dashboard", { waitUntil: "commit" })

    await expect(page.locator(".animate-pulse").first()).toBeVisible()
    // And they give way to the real thing once it lands.
    await expect(page.getByTestId("engine-row-docker")).toBeVisible({
      timeout: 10000,
    })
  })

  test("plan usage stays at the top, above the engine sections", async ({
    page,
  }) => {
    await mockRepositories(page, [MOCK_REPO])
    await mockAnalyses(page, [MOCK_ANALYSIS])
    await mockIssues(page, [])

    await page.goto("/dashboard")

    // Account-wide, so it is not scoped to any one engine's section.
    await expect(page.getByText("Plan Usage")).toBeVisible()
    await expect(
      page.getByTestId("section-ci").getByText("Plan Usage"),
    ).not.toBeAttached()
  })
})
