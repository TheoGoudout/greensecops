import { expect, test } from "@playwright/test"
import {
  MOCK_CLOUD_FINDING,
  MOCK_PR_OPEN,
  MOCK_REPO,
  mockBilling,
  mockCloudAccounts,
  mockEvents,
  mockFixes,
  mockRepositories,
  mockUserMe,
} from "./utils/mocks"

test.describe("Cloud", () => {
  test.beforeEach(async ({ page }) => {
    await mockUserMe(page)
    await mockEvents(page)
    await mockBilling(page)
    await mockRepositories(page, [MOCK_REPO])
    await mockFixes(page, [], [MOCK_PR_OPEN])
    // The Cloud tab lives under Infrastructure, whose sibling tab loads
    // Terraform roots; without this the page hangs on a real request.
    await page.route("**/api/v1/terraform/roots**", (route) => {
      route.fulfill({ json: [] })
    })
  })

  test("lists connected accounts with their grade", async ({ page }) => {
    await mockCloudAccounts(page)

    await page.goto(`/infrastructure/${MOCK_REPO.id}/cloud`)

    await expect(page.getByText("prod")).toBeVisible()
    await expect(page.getByText("C", { exact: true })).toBeVisible()
  })

  test("empty state when no accounts are connected", async ({ page }) => {
    await mockCloudAccounts(page, [])

    await page.goto(`/infrastructure/${MOCK_REPO.id}/cloud`)

    await expect(
      page.getByText("No cloud accounts connected", { exact: false }),
    ).toBeVisible()
  })

  test("expanding an account shows its open findings", async ({ page }) => {
    await mockCloudAccounts(page)

    await page.goto(`/infrastructure/${MOCK_REPO.id}/cloud`)
    await page.getByTitle("Expand account").first().click()

    await expect(page.getByText("s3_bucket_public_read")).toBeVisible()
    await expect(
      page.getByText("S3 bucket acme-data allows public read access."),
    ).toBeVisible()
    // The finding's resource type/id is the subtitle's primary label.
    await expect(
      page.getByText("aws_s3_bucket: acme-data", { exact: false }),
    ).toBeVisible()
  })

  test("ignoring and unignoring a finding round-trips its status", async ({
    page,
  }) => {
    await mockCloudAccounts(page)

    await page.goto(`/infrastructure/${MOCK_REPO.id}/cloud`)
    await page.getByTitle("Expand account").first().click()

    const ignoreRequest = page.waitForRequest(
      (r) =>
        r.url().includes(`/cloud/findings/${MOCK_CLOUD_FINDING.id}/ignore`) &&
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
        r.url().includes(`/cloud/findings/${MOCK_CLOUD_FINDING.id}/ignore`) &&
        r.method() === "DELETE",
    )
    await unignoreButton.click()
    await unignoreRequest

    await expect(
      page.getByRole("button", { name: "Ignore" }).first(),
    ).toBeVisible()
  })

  test("scanning an account queues a scan", async ({ page }) => {
    await mockCloudAccounts(page)

    await page.goto(`/infrastructure/${MOCK_REPO.id}/cloud`)

    const request = page.waitForRequest(
      (r) => r.url().includes("/scan") && r.method() === "POST",
    )
    await page.getByRole("button", { name: "Scan now" }).first().click()
    await request
  })
})
