import { expect, test } from "@playwright/test"
import {
  MOCK_ANSIBLE_PROJECT,
  MOCK_PR_OPEN,
  MOCK_REPO,
  mockAnsibleProjects,
  mockBilling,
  mockEvents,
  mockFixes,
  mockRepositories,
  mockUserMe,
} from "./utils/mocks"

test.describe("Ansible", () => {
  test.beforeEach(async ({ page }) => {
    await mockUserMe(page)
    await mockEvents(page)
    await mockBilling(page)
    await mockRepositories(page, [MOCK_REPO])
    await mockFixes(page, [], [MOCK_PR_OPEN])
    // The Ansible tab lives under Infrastructure, whose sibling tab loads
    // Terraform roots; without this the page hangs on a real request.
    await page.route("**/api/v1/terraform/roots**", (route) => {
      route.fulfill({ json: [] })
    })
  })

  test("lists registered projects with their grade", async ({ page }) => {
    await mockAnsibleProjects(page)

    await page.goto(`/infrastructure/${MOCK_REPO.id}/ansible`)

    // "" is a legal root_path for this engine and renders as the repo root.
    // Scoped to the card title: a bare "/" also matches the router devtools
    // panel dev mode injects, which is not what this asserts.
    await expect(
      page.locator("span.truncate").filter({ hasText: /^\/$/ }),
    ).toBeVisible()
    await expect(page.getByText("deploy/ansible")).toBeVisible()
    await expect(page.getByText("C", { exact: true })).toBeVisible()
  })

  test("empty state when no projects are registered", async ({ page }) => {
    await mockAnsibleProjects(page, [])

    await page.goto(`/infrastructure/${MOCK_REPO.id}/ansible`)

    await expect(
      page.getByText("No Ansible projects registered for this repository."),
    ).toBeVisible()
  })

  test("expanding a project shows its source and findings", async ({
    page,
  }) => {
    await mockAnsibleProjects(page)

    await page.goto(`/infrastructure/${MOCK_REPO.id}/ansible`)
    await page.getByTitle("Expand project").first().click()

    await expect(page.getByText("roles/docker/tasks/main.yml")).toBeVisible()
    // The classifier's kind is surfaced as a chip.
    await expect(page.getByText("tasks", { exact: true })).toBeVisible()
    await expect(
      page.getByText("Shell command interpolates", { exact: false }),
    ).toBeVisible()
  })

  test("a file-level finding is still shown when it names no line", async ({
    page,
  }) => {
    await mockAnsibleProjects(page)

    await page.goto(`/infrastructure/${MOCK_REPO.id}/ansible`)
    await page.getByTitle("Expand project").first().click()

    // galaxy_requirement_unpinned carries no task and no line; FileViewer
    // groups those separately rather than dropping them.
    await expect(
      page.getByText("Collection community.docker is not pinned"),
    ).toBeVisible()
  })

  test("generating fixes for the whole project queues the task", async ({
    page,
  }) => {
    await mockAnsibleProjects(page)

    await page.goto(`/infrastructure/${MOCK_REPO.id}/ansible`)
    await page.getByTitle("Expand project").first().click()

    const request = page.waitForRequest(
      (r) =>
        r
          .url()
          .includes(`/ansible/projects/${MOCK_ANSIBLE_PROJECT.id}/fixes`) &&
        r.method() === "POST",
    )
    await page.getByRole("button", { name: "Generate all fixes" }).click()
    await request
  })

  test("a ready fix offers PR delivery", async ({ page }) => {
    await mockAnsibleProjects(page)

    await page.goto(`/infrastructure/${MOCK_REPO.id}/ansible`)
    await page.getByTitle("Expand project").first().click()

    const request = page.waitForRequest(
      (r) =>
        r
          .url()
          .includes(
            `/ansible/projects/${MOCK_ANSIBLE_PROJECT.id}/deliveries`,
          ) && r.method() === "POST",
    )
    // No PR exists on this project's branch yet, so the button offers to make
    // one rather than to update or reopen.
    await page.getByRole("button", { name: "Create PR" }).click()
    await request
  })

  test("scanning a project queues a scan", async ({ page }) => {
    await mockAnsibleProjects(page)

    await page.goto(`/infrastructure/${MOCK_REPO.id}/ansible`)

    const request = page.waitForRequest(
      (r) => r.url().includes("/scan") && r.method() === "POST",
    )
    await page.getByRole("button", { name: "Scan now" }).first().click()
    await request
  })

  test("the engine has its own Infrastructure index", async ({ page }) => {
    await mockAnsibleProjects(page)

    await page.goto("/infrastructure/ansible")

    // Its own page rather than a section of the Terraform one: the heading is
    // the engine's, and the register form takes a project, not a root.
    await expect(page.getByRole("heading", { name: "Ansible" })).toBeVisible()
    await expect(
      page.getByRole("button", { name: "Add project" }),
    ).toBeVisible()
    await expect(page.getByText("acme/web-app")).toBeVisible()
  })

  test("the Ansible index empty state explains the blank path", async ({
    page,
  }) => {
    await mockAnsibleProjects(page, [])

    await page.goto("/infrastructure/ansible")

    // The blank-path case is this engine's alone — a Terraform root must name
    // a folder — so the empty state is where a reader finds out.
    await expect(
      page.getByText("leave the path blank", { exact: false }),
    ).toBeVisible()
  })

  test("the Terraform index no longer lists Ansible projects", async ({
    page,
  }) => {
    await mockAnsibleProjects(page)
    await page.route("**/api/v1/terraform/roots**", (route) => {
      route.fulfill({ json: [] })
    })

    await page.goto("/infrastructure")

    await expect(page.getByRole("heading", { name: "Terraform" })).toBeVisible()
    await expect(page.getByText("Ansible projects")).toHaveCount(0)
  })

  test("the Infrastructure tab bar offers Ansible", async ({ page }) => {
    await mockAnsibleProjects(page)

    await page.goto(`/infrastructure/${MOCK_REPO.id}/terraform`)

    const tabs = page.locator("nav.border-b")
    await expect(tabs.getByRole("link", { name: "Ansible" })).toBeVisible()
  })

  test("the PRs tab carries Terraform and Ansible sections", async ({
    page,
  }) => {
    await mockAnsibleProjects(page)

    await page.goto(`/infrastructure/${MOCK_REPO.id}/pull-requests`)

    await expect(page.getByRole("heading", { name: "Terraform" })).toBeVisible()
    await expect(page.getByRole("heading", { name: "Ansible" })).toBeVisible()
    // Each section points the reader at the tab that produces its PRs, and
    // Ansible's analysis lives on a tab named after the engine.
    await expect(
      page.getByText("No Ansible PRs yet.", { exact: false }),
    ).toBeVisible()
  })
})
