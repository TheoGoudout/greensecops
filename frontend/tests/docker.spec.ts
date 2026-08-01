import { expect, test } from "@playwright/test"
import {
  MOCK_DOCKER_PR,
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

    await expect(
      page.getByText(
        "No Docker targets yet. One is created automatically for every repository the GitHub App syncs.",
      ),
    ).toBeVisible()
  })

  test("clicking a repo lands on the analysis tab", async ({ page }) => {
    await mockDockerTargets(page)

    await page.goto("/docker")
    await page.getByText("acme/web-app").click()

    await expect(page).toHaveURL(new RegExp(`/docker/${MOCK_REPO.id}/analysis`))
    await expect(page.getByText("/ (repository root)")).toBeVisible()
    await expect(page.getByText("services/api")).toBeVisible()
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

    await page.goto("/docker/badges")

    await expect(
      page.getByRole("heading", { name: "Docker Badges" }),
    ).toBeVisible()
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
      ["/docker/badges", "Docker Badges - GreenSecOps"],
      [`/docker/${MOCK_REPO.id}/analysis`, "Docker analysis - GreenSecOps"],
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
    await page.route("**/api/v1/terraform-roots/**", (route) => {
      route.fulfill({ json: [] })
    })

    await page.goto(`/infrastructure/${MOCK_REPO.id}/terraform`)

    // Scope to the page's tab bar — the sidebar now carries its own Docker
    // link, which is exactly where that entry is supposed to live.
    const tabs = page.locator("nav.border-b")
    await expect(tabs.getByRole("link", { name: "Terraform" })).toBeVisible()
    await expect(tabs.getByRole("link", { name: "Cloud" })).toBeVisible()
    await expect(tabs.getByRole("link", { name: "Docker" })).toHaveCount(0)
  })
})
