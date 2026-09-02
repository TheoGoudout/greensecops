import { expect, test } from "@playwright/test"
import {
  MOCK_ANSIBLE_FINDING,
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

    await expect(
      page.getByText("roles/docker/tasks/main.yml").first(),
    ).toBeVisible()
    // The classifier's kind is surfaced as a chip.
    await expect(page.getByText("tasks", { exact: true })).toBeVisible()
    // The finding shows up twice by design: annotated inline by FileViewer
    // and again in the AnsibleFindingRow list below it.
    await expect(
      page.getByText("Shell command interpolates", { exact: false }).first(),
    ).toBeVisible()
    await expect(
      page.getByText("Shell command interpolates", { exact: false }),
    ).toHaveCount(2)
    // The finding's task name is part of the subtitle.
    await expect(page.getByText("Log in to ECR").first()).toBeVisible()
  })

  test("a file-level finding is still shown when it names no line", async ({
    page,
  }) => {
    await mockAnsibleProjects(page)

    await page.goto(`/infrastructure/${MOCK_REPO.id}/ansible`)
    await page.getByTitle("Expand project").first().click()

    // galaxy_requirement_unpinned carries no task and no line; FileViewer
    // groups those separately rather than dropping them. It also shows up a
    // second time in the AnsibleFindingRow list below, same as every finding.
    await expect(
      page.getByText("Collection community.docker is not pinned").first(),
    ).toBeVisible()
    await expect(
      page.getByText("Collection community.docker is not pinned"),
    ).toHaveCount(2)
  })

  test("ignoring and unignoring a finding round-trips its status", async ({
    page,
  }) => {
    await mockAnsibleProjects(page)

    await page.goto(`/infrastructure/${MOCK_REPO.id}/ansible`)
    await page.getByTitle("Expand project").first().click()

    const ignoreRequest = page.waitForRequest(
      (r) =>
        r
          .url()
          .includes(`/ansible/findings/${MOCK_ANSIBLE_FINDING.id}/ignore`) &&
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
        r
          .url()
          .includes(`/ansible/findings/${MOCK_ANSIBLE_FINDING.id}/ignore`) &&
        r.method() === "DELETE",
    )
    await unignoreButton.click()
    await unignoreRequest

    await expect(
      page.getByRole("button", { name: "Ignore" }).first(),
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
    await page
      .getByRole("button", { name: /Generate fixes/ })
      .first()
      .click()
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
    await page.getByRole("button", { name: "Create PR" }).first().click()
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

  test("a quota refusal says what the quota is", async ({ page }) => {
    // A quota 402 arrives as an *object* carrying a sentence naming what was
    // used, the cap, when it resets and what to do next. The toast helper read
    // only a plain-string detail, so it showed the generic title and nothing
    // else — the most useful message the API sends was the one message these
    // buttons could not show.
    await mockAnsibleProjects(page)
    // Registered last so it wins: Playwright matches routes last-first.
    await page.route(
      (url) =>
        url.pathname.includes("/ansible/projects") &&
        url.pathname.endsWith("/scans"),
      (route) => {
        if (route.request().method() !== "POST") return route.fallback()
        route.fulfill({
          status: 402,
          json: {
            detail: {
              code: "quota_exceeded",
              message:
                "You have used all 100 analyses on the Free plan this period.",
              meter: "analyses",
              tier: "free",
            },
          },
        })
      },
    )

    await page.goto(`/infrastructure/${MOCK_REPO.id}/ansible`)
    await page.getByRole("button", { name: "Scan now" }).first().click()

    await expect(page.getByText("Could not queue scan")).toBeVisible()
    await expect(
      page.getByText("You have used all 100 analyses on the Free plan"),
    ).toBeVisible()
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

  test("the Infrastructure tab bar keeps Terraform and Ansible separate", async ({
    page,
  }) => {
    await mockAnsibleProjects(page)

    await page.goto(`/infrastructure/${MOCK_REPO.id}/terraform`)
    const terraformTabs = page.locator("nav.border-b")
    await expect(
      terraformTabs.getByRole("link", { name: "Ansible" }),
    ).toHaveCount(0)

    await page.goto(`/infrastructure/${MOCK_REPO.id}/ansible`)
    const ansibleTabs = page.locator("nav.border-b")
    await expect(
      ansibleTabs.getByRole("link", { name: "Analysis" }),
    ).toBeVisible()
    await expect(ansibleTabs.getByRole("link", { name: "Cloud" })).toHaveCount(
      0,
    )
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
