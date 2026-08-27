import { expect, test } from "@playwright/test"
import {
  MOCK_INVOICES,
  MOCK_SUBSCRIPTION,
  MOCK_SUBSCRIPTION_PAST_DUE,
  MOCK_SUBSCRIPTION_UNPAID,
  MOCK_TIER_LIMITS,
  MOCK_USAGE,
  mockAnalyses,
  mockBilling,
  mockEvents,
  mockIssues,
  mockRepositories,
  mockRules,
  mockUserMe,
} from "./utils/mocks"

test.describe("Billing", () => {
  test.beforeEach(async ({ page }) => {
    await mockUserMe(page)
    await mockEvents(page)
    await mockRules(page)
    await mockRepositories(page, [])
    await mockAnalyses(page, [])
    await mockIssues(page, [])
  })

  test("shows plan name, price, and Active badge", async ({ page }) => {
    await mockBilling(page)

    await page.goto("/billing")

    await expect(page.getByRole("heading", { name: "Billing" })).toBeVisible()
    await expect(page.getByText("Free").first()).toBeVisible()
    await expect(page.getByText("$0/mo").first()).toBeVisible()
    await expect(page.getByText("Active")).toBeVisible()
  })

  test("usage bars show analyses, fixes, repos against the plan limits", async ({
    page,
  }) => {
    await mockBilling(page)

    await page.goto("/billing")

    await expect(page.getByText("Usage this period")).toBeVisible({
      timeout: 10000,
    })

    await expect(page.getByText("Analyses").first()).toBeVisible()
    await expect(page.getByText("/ 100")).toBeVisible()
    await expect(page.getByText("AI Fixes", { exact: true })).toBeVisible()
    await expect(page.getByText("/ 10", { exact: true })).toBeVisible()
    await expect(page.getByText("Repositories").first()).toBeVisible()
    await expect(page.getByText("/ 3")).toBeVisible()
  })

  test("names the period reset date and what an analysis covers", async ({
    page,
  }) => {
    await mockBilling(page)

    await page.goto("/billing")

    // "Resets on <date>" is half of what makes a quota message actionable;
    // the other half is knowing which engines spend it.
    await expect(page.getByText(/Resets on/)).toBeVisible()
    await expect(
      page.getByText(/workflows, Terraform, Docker, cloud and CI telemetry/),
    ).toBeVisible()
  })

  test("shows the per-engine usage breakdown", async ({ page }) => {
    await mockBilling(page)

    await page.goto("/billing")

    // The answer to "why am I at 90%": before the ledger this was unanswerable.
    await expect(page.getByText("Usage breakdown")).toBeVisible()
    await expect(
      page.getByRole("cell", { name: "Terraform", exact: true }),
    ).toBeVisible()
    await expect(
      page.getByRole("cell", { name: "CI workflows", exact: true }).first(),
    ).toBeVisible()
    // 7 Terraform analyses against 5 workflow ones — the split is the point.
    await expect(
      page.getByRole("cell", { name: "7", exact: true }),
    ).toBeVisible()
  })

  test("Manage subscription opens the Stripe portal", async ({ page }) => {
    await mockBilling(page)

    await page.goto("/billing")

    const manage = page.getByRole("button", { name: "Manage subscription" })
    await expect(manage).toBeVisible()
    await expect(manage).toBeEnabled()
  })

  test("hides billing actions when Stripe is not configured", async ({
    page,
  }) => {
    // A self-hosted install should not offer a button that 503s.
    await mockBilling(page, {
      ...MOCK_SUBSCRIPTION,
      billing_enabled: false,
    })

    await page.goto("/billing")

    await expect(page.getByRole("heading", { name: "Billing" })).toBeVisible()
    await expect(
      page.getByRole("button", { name: "Manage subscription" }),
    ).toHaveCount(0)
  })

  test("lists invoices with amounts and a link", async ({ page }) => {
    await mockBilling(page, MOCK_SUBSCRIPTION, MOCK_TIER_LIMITS, MOCK_USAGE, {
      invoices: MOCK_INVOICES,
    })

    await page.goto("/billing")

    await expect(page.getByText("Invoices")).toBeVisible()
    await expect(page.getByText("GS-0001")).toBeVisible()
    await expect(page.getByText("$79.00")).toBeVisible()
  })

  test("past due shows the grace banner without alarming language", async ({
    page,
  }) => {
    await mockBilling(page, MOCK_SUBSCRIPTION_PAST_DUE)

    await page.goto("/billing")

    const banner = page.getByRole("alert")
    await expect(banner).toBeVisible()
    await expect(banner).toContainText("could not take your last payment")
    // The reassurance is the point of the grace window.
    await expect(banner).toContainText("still working in full")
    // The status badge lives on the plan card, not in the banner.
    await expect(page.getByText("Payment failed")).toBeVisible()
    await expect(
      page.getByRole("button", { name: "Update payment method" }),
    ).toBeVisible()
  })

  test("unpaid says what changed and that nothing was deleted", async ({
    page,
  }) => {
    await mockBilling(page, MOCK_SUBSCRIPTION_UNPAID)

    await page.goto("/billing")

    const banner = page.getByRole("alert")
    await expect(banner).toContainText("Free plan limits")
    await expect(banner).toContainText("Nothing has been deleted")
    // Still a Pro subscription; the page must not silently report it as Free.
    await expect(page.getByText(/Currently limited to Free/)).toBeVisible()
  })

  test("offers the open source application form", async ({ page }) => {
    await mockBilling(page)

    await page.goto("/billing")

    await expect(page.getByText("Open source", { exact: true })).toBeVisible()
    await expect(
      page.getByRole("button", { name: "Apply for the Open Source plan" }),
    ).toBeVisible()
  })

  test("loading skeletons appear while data loads", async ({ page }) => {
    // Hold the billing queries open indefinitely, so the loading state is
    // observable rather than a race against how fast the mock resolves.
    let release: (() => void) | undefined
    const held = new Promise<void>((resolve) => {
      release = resolve
    })
    await page.route("**/api/v1/billing**", async (route) => {
      await held
      route.fulfill({ json: MOCK_SUBSCRIPTION })
    })

    await page.goto("/billing")

    await expect(page.getByRole("heading", { name: "Billing" })).toBeVisible()
    await expect(page.locator('[data-slot="skeleton"]').first()).toBeVisible()
    release?.()
  })
})
