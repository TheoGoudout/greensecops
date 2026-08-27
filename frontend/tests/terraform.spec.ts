import { expect, test } from "@playwright/test"
import {
  MOCK_PR_OPEN,
  MOCK_REPO,
  MOCK_TERRAFORM_FINDING,
  MOCK_TERRAFORM_ROOT,
  mockBilling,
  mockEvents,
  mockFixes,
  mockRepositories,
  mockTerraformRoots,
  mockUserMe,
} from "./utils/mocks"

test.describe("Terraform", () => {
  test.beforeEach(async ({ page }) => {
    await mockUserMe(page)
    await mockEvents(page)
    await mockBilling(page)
    await mockRepositories(page, [MOCK_REPO])
    await mockFixes(page, [], [MOCK_PR_OPEN])
  })

  test("lists registered roots with their grade", async ({ page }) => {
    await mockTerraformRoots(page)

    await page.goto(`/infrastructure/${MOCK_REPO.id}/terraform`)

    await expect(page.getByText("deploy/terraform")).toBeVisible()
    await expect(page.getByText("C", { exact: true })).toBeVisible()
  })

  test("empty state when no roots are configured", async ({ page }) => {
    await mockTerraformRoots(page, [])

    await page.goto(`/infrastructure/${MOCK_REPO.id}/terraform`)

    await expect(
      page.getByText("No Terraform roots configured for this repository.", {
        exact: false,
      }),
    ).toBeVisible()
  })

  test("expanding a root shows its files and findings", async ({ page }) => {
    await mockTerraformRoots(page)

    await page.goto(`/infrastructure/${MOCK_REPO.id}/terraform`)
    await page.getByTitle("Expand root").first().click()

    // The finding shows up twice by design: annotated inline by FileViewer
    // and again in the TerraformFindingRow list below it.
    await expect(page.getByText("missing_remote_backend").first()).toBeVisible()
    await expect(
      page
        .getByText("The root module declares no backend or cloud block.")
        .first(),
    ).toBeVisible()
    await expect(page.getByText("missing_remote_backend")).toHaveCount(2)
    // The finding's resource address is the subtitle's primary label.
    await expect(
      page.locator(".rounded-md.border.divide-y").getByText("terraform"),
    ).toBeVisible()
  })

  test("generating fixes for the whole root queues the task", async ({
    page,
  }) => {
    await mockTerraformRoots(page)

    await page.goto(`/infrastructure/${MOCK_REPO.id}/terraform`)
    await page.getByTitle("Expand root").first().click()

    const request = page.waitForRequest(
      (r) =>
        r.url().includes(`/terraform/roots/${MOCK_TERRAFORM_ROOT.id}/fixes`) &&
        r.method() === "POST",
    )
    await page.getByRole("button", { name: "Generate all fixes" }).click()
    await request
  })

  test("ignoring and unignoring a finding round-trips its status", async ({
    page,
  }) => {
    await mockTerraformRoots(page)

    await page.goto(`/infrastructure/${MOCK_REPO.id}/terraform`)
    await page.getByTitle("Expand root").first().click()

    const ignoreRequest = page.waitForRequest(
      (r) =>
        r
          .url()
          .includes(
            `/terraform/findings/${MOCK_TERRAFORM_FINDING.id}/ignore`,
          ) && r.method() === "PUT",
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
          .includes(
            `/terraform/findings/${MOCK_TERRAFORM_FINDING.id}/ignore`,
          ) && r.method() === "DELETE",
    )
    await unignoreButton.click()
    await unignoreRequest

    await expect(
      page.getByRole("button", { name: "Ignore" }).first(),
    ).toBeVisible()
  })

  test("scanning a root queues a scan", async ({ page }) => {
    await mockTerraformRoots(page)

    await page.goto(`/infrastructure/${MOCK_REPO.id}/terraform`)

    const request = page.waitForRequest(
      (r) => r.url().includes("/scan") && r.method() === "POST",
    )
    await page.getByRole("button", { name: "Scan now" }).first().click()
    await request
  })
})
