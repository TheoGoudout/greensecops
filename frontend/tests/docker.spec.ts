import { expect, test } from "@playwright/test"
import {
  MOCK_DOCKER_FINDING,
  MOCK_DOCKER_PR,
  MOCK_DOCKER_RUNTIME_BUILD_UNATTRIBUTED,
  MOCK_DOCKER_TARGET,
  MOCK_PR_OPEN,
  MOCK_REPO,
  mockBilling,
  mockDockerTargets,
  mockEvents,
  mockFixes,
  mockRepositories,
  mockUserMe,
} from "./utils/mocks"

test.describe("Docker", () => {
  test.beforeEach(async ({ page }) => {
    await mockUserMe(page)
    await mockEvents(page)
    await mockBilling(page)
    await mockRepositories(page, [MOCK_REPO])
    await mockFixes(page, [], [MOCK_PR_OPEN, MOCK_DOCKER_PR])
  })

  test("list page groups targets by repo with worst grade", async ({
    page,
  }) => {
    await mockDockerTargets(page)

    await page.goto("/docker")

    await expect(page.getByRole("heading", { name: "Docker" })).toBeVisible()
    await expect(page.getByText("acme/web-app")).toBeVisible()
    await expect(page.getByText("2 targets")).toBeVisible()
    // Worst of the two target grades (C and E) is what the row surfaces.
    await expect(page.getByText("E", { exact: true })).toBeVisible()
  })

  test("empty state when no targets", async ({ page }) => {
    await mockDockerTargets(page, [])

    await page.goto("/docker")

    // Targets are registered by hand now, so the empty state explains the add
    // form rather than promising one per synced repository. Matched on the
    // leading sentence: the rest of the copy is broken up by an inline <code>.
    await expect(page.getByText("No Docker targets configured.")).toBeVisible()
  })

  test("clicking a repo lands on the analysis tab", async ({ page }) => {
    await mockDockerTargets(page)

    await page.goto("/docker")
    await page.getByText("acme/web-app").click()

    await expect(page).toHaveURL(new RegExp(`/docker/${MOCK_REPO.id}/analysis`))
    await expect(page.getByText("/ (repository root)")).toBeVisible()
    await expect(page.getByText("services/api")).toBeVisible()
  })

  test("the repo header shows the Docker average, not the worst target", async ({
    page,
  }) => {
    await mockDockerTargets(page)

    await page.goto(`/docker/${MOCK_REPO.id}/analysis`)

    // MOCK_REPO's Docker average is D; its two targets grade C and E. The
    // header used to render `worstGrade` over the target list, so it showed E
    // — one bad target setting the grade for all of them.
    const header = page.getByTestId("repo-page-header")
    await expect(header.getByText("D", { exact: true })).toBeVisible()
    await expect(header.getByText("E", { exact: true })).toHaveCount(0)
  })

  test("expanding a target shows its files and findings", async ({ page }) => {
    await mockDockerTargets(page)

    await page.goto(`/docker/${MOCK_REPO.id}/analysis`)

    await page.getByLabel("Expand target").first().click()

    // The finding shows up twice by design: annotated inline by
    // DockerFileViewer and again in the DockerFindingRow list below it.
    await expect(page.getByText("unpinned-base-image").first()).toBeVisible()
    await expect(
      page
        .getByText("Base image node:latest is not pinned to a digest")
        .first(),
    ).toBeVisible()
    await expect(page.getByText("unpinned-base-image")).toHaveCount(2)
  })

  test("ignoring and unignoring a finding round-trips its status", async ({
    page,
  }) => {
    await mockDockerTargets(page)

    await page.goto(`/docker/${MOCK_REPO.id}/analysis`)
    await page.getByLabel("Expand target").first().click()

    const ignoreRequest = page.waitForRequest(
      (r) =>
        r.url().includes(`/docker/findings/${MOCK_DOCKER_FINDING.id}/ignore`) &&
        r.method() === "PUT",
    )
    await page.getByRole("button", { name: "Ignore" }).first().click()
    await ignoreRequest

    await expect(
      page.getByText("ignored", { exact: true }).first(),
    ).toBeVisible()
    const unignoreButton = page
      .getByRole("button", { name: "Unignore" })
      .first()
    await expect(unignoreButton).toBeVisible()

    const unignoreRequest = page.waitForRequest(
      (r) =>
        r.url().includes(`/docker/findings/${MOCK_DOCKER_FINDING.id}/ignore`) &&
        r.method() === "DELETE",
    )
    await unignoreButton.click()
    await unignoreRequest

    await expect(
      page.getByRole("button", { name: "Ignore" }).first(),
    ).toBeVisible()
  })

  test("PRs tab lists only Docker PRs", async ({ page }) => {
    await mockDockerTargets(page)

    await page.goto(`/docker/${MOCK_REPO.id}/pull-requests`)

    await expect(page.getByText("acme/web-app/pull/77")).toBeVisible()
    // The CI-workflow PR belongs to the Repositories section, not here.
    await expect(page.getByText("acme/web-app/pull/42")).toHaveCount(0)
  })

  test("scan history tab shows past scans", async ({ page }) => {
    await mockDockerTargets(page)

    await page.goto(`/docker/${MOCK_REPO.id}/scans`)

    await expect(page.getByText("completed")).toBeVisible()
    await expect(page.getByText("2 files")).toBeVisible()
    await expect(
      page.getByText("Could not fetch Docker files from GitHub"),
    ).toBeVisible()
    // The second target has never been scanned.
    await expect(
      page.getByText("Never scanned. Trigger one from the Analysis tab."),
    ).toBeVisible()
  })

  test("badges page shows copyable markdown per target", async ({ page }) => {
    await mockDockerTargets(page)

    // Docker badges moved onto the shared Badges page as a tab; the old URL
    // redirects there.
    await page.goto("/docker/badges")
    await expect(page).toHaveURL(/\/badges\/docker/)

    await expect(page.getByRole("heading", { name: "Badges" })).toBeVisible()
    await expect(
      page.getByText(`/api/v1/badges/docker/${MOCK_DOCKER_TARGET.id}.svg`),
    ).toBeVisible()
    await expect(
      page.getByRole("button", { name: "Copy Markdown" }).first(),
    ).toBeVisible()
  })

  test("page titles are correct", async ({ page }) => {
    // Five full navigations in one test — well past the default budget on a
    // cold dev server.
    test.slow()
    await mockDockerTargets(page)

    const pages: Array<[string, string]> = [
      ["/docker", "Docker - GreenSecOps"],
      [`/docker/${MOCK_REPO.id}/analysis`, "Docker analysis - GreenSecOps"],
      [`/docker/${MOCK_REPO.id}/runtime`, "Docker runtime - GreenSecOps"],
      [`/docker/${MOCK_REPO.id}/pull-requests`, "Docker PRs - GreenSecOps"],
      [`/docker/${MOCK_REPO.id}/scans`, "Docker scan history - GreenSecOps"],
    ]

    for (const [path, expectedTitle] of pages) {
      await page.goto(path)
      await expect(page).toHaveTitle(expectedTitle)
    }
  })

  test("old Infrastructure Docker URL redirects to the new section", async ({
    page,
  }) => {
    await mockDockerTargets(page)

    await page.goto(`/infrastructure/${MOCK_REPO.id}/docker`)

    await expect(page).toHaveURL(new RegExp(`/docker/${MOCK_REPO.id}/analysis`))
  })

  test("Infrastructure no longer offers a Docker tab", async ({ page }) => {
    await mockDockerTargets(page)
    await page.route("**/api/v1/terraform/roots**", (route) => {
      route.fulfill({ json: [] })
    })

    await page.goto(`/infrastructure/${MOCK_REPO.id}/terraform`)

    // Scope to the page's tab bar — the sidebar now carries its own Docker
    // link, which is exactly where that entry is supposed to live.
    const tabs = page.locator("nav.border-b")
    await expect(tabs.getByRole("link", { name: "Analysis" })).toBeVisible()
    await expect(tabs.getByRole("link", { name: "Cloud" })).toBeVisible()
    await expect(tabs.getByRole("link", { name: "Docker" })).toHaveCount(0)
  })

  // ─── Runtime tab ───────────────────────────────────────────────────────────

  test("runtime tab shows measured builds and their findings", async ({
    page,
  }) => {
    await mockDockerTargets(page)

    await page.goto(`/docker/${MOCK_REPO.id}/runtime`)
    await page.getByLabel("Expand target").first().click()

    await expect(page.getByText("run #12345678901")).toBeVisible()
    await expect(page.getByText("2.4 GB")).toBeVisible()
    await expect(page.getByText("18%")).toBeVisible()
    await expect(
      page.getByText("Container ran with no memory limit"),
    ).toBeVisible()
    // The measurement itself, not just the advice.
    await expect(
      page.getByText(
        "container 'api' peaked at 420 MB with no memory limit set",
      ),
    ).toBeVisible()
  })

  test("runtime tab renders per-container measurements", async ({ page }) => {
    await mockDockerTargets(page)

    await page.goto(`/docker/${MOCK_REPO.id}/runtime`)
    await page.getByLabel("Expand target").first().click()

    const row = page.getByRole("row", { name: /api/ })
    await expect(row).toBeVisible()
    await expect(row.getByText("420 MB")).toBeVisible()
    // 0 is "explicitly unlimited", which is what the finding fired on.
    await expect(row.getByText("none")).toBeVisible()
  })

  test("selecting a finding queues a runtime fix", async ({ page }) => {
    await mockDockerTargets(page)

    await page.goto(`/docker/${MOCK_REPO.id}/runtime`)
    await page.getByLabel("Expand target").first().click()

    await page.getByLabel("Select container_unbounded_memory").check()
    await page.getByRole("button", { name: "Fix 1 finding" }).click()

    await expect(page.getByText("Fix generation queued")).toBeVisible()
  })

  test("findings from a build with no dockerfile_path cannot be selected", async ({
    page,
  }) => {
    // Without the join back to source there is no file to rewrite, so the row
    // still renders the measurement but offers no checkbox.
    await mockDockerTargets(page, undefined, {
      runtime: [MOCK_DOCKER_RUNTIME_BUILD_UNATTRIBUTED],
    })

    await page.goto(`/docker/${MOCK_REPO.id}/runtime`)
    await page.getByLabel("Expand target").first().click()

    await expect(page.getByText("(no dockerfile_path reported)")).toBeVisible()
    await expect(
      page.getByText("Container ran with no memory limit"),
    ).toBeVisible()
    await expect(
      page.getByLabel("Select container_unbounded_memory"),
    ).toHaveCount(0)
  })

  test("runtime tab explains itself when nothing has been measured", async ({
    page,
  }) => {
    await mockDockerTargets(page, undefined, { runtime: [] })

    await page.goto(`/docker/${MOCK_REPO.id}/runtime`)
    await page.getByLabel("Expand target").first().click()

    await expect(page.getByText(/No measured builds yet/)).toBeVisible()
  })
})
