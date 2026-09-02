import { expect, type Locator, test } from "@playwright/test"
import {
  MOCK_PR_OPEN,
  MOCK_REPO,
  MOCK_TERRAFORM_FINDING,
  MOCK_TERRAFORM_FIX,
  MOCK_TERRAFORM_ROOT,
  mockBilling,
  mockEvents,
  mockFixes,
  mockRepositories,
  mockTerraformRoots,
  mockUserMe,
  quotaSpent,
} from "./utils/mocks"

/**
 * Hover a disabled action to read its reason.
 *
 * A disabled `<button>` takes no pointer events, which is exactly why
 * `EngineActionButton` wraps it in a focusable span for the tooltip to hang
 * off — so the hover has to land on that span, not on the button inside it.
 */
async function reasonFor(button: Locator) {
  await button
    .locator("xpath=ancestor::span[@data-slot='tooltip-trigger']")
    .hover()
}

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
    // No fixes yet: the button queues only files that have none, so a root
    // whose one file already carries a written fix is the *other* test.
    await mockTerraformRoots(page, [MOCK_TERRAFORM_ROOT], { fixes: [] })

    await page.goto(`/infrastructure/${MOCK_REPO.id}/terraform`)
    await page.getByTitle("Expand root").first().click()

    const request = page.waitForRequest(
      (r) =>
        r.url().includes(`/terraform/roots/${MOCK_TERRAFORM_ROOT.id}/fixes`) &&
        r.method() === "POST",
    )
    await page.getByRole("button", { name: /Generate fixes/ }).click()
    await request
  })

  test("a file whose fix is already written offers to regenerate it", async ({
    page,
  }) => {
    // `prepare_pending_fix` re-queues only a `failed` fix, so a plain generate
    // over a file that already has one is accepted, queues nothing, and used to
    // toast "Fix generation queued" over a request that did nothing.
    await mockTerraformRoots(page)

    await page.goto(`/infrastructure/${MOCK_REPO.id}/terraform`)

    const bar = page.getByRole("button", { name: /Generate fixes/ }).first()
    await expect(bar).toBeDisabled()
    await reasonFor(bar)
    await expect(
      page.getByText("Every file with findings already has a fix"),
    ).toBeVisible()

    await page.getByTitle("Expand root").first().click()
    const request = page.waitForRequest(
      (r) =>
        r.url().includes(`/terraform/roots/${MOCK_TERRAFORM_ROOT.id}/fixes`) &&
        r.url().includes("force=true") &&
        r.method() === "POST",
    )
    await page.getByRole("button", { name: "Regenerate fix" }).click()
    await request
  })

  test("removing a root is refused while it is scanning", async ({ page }) => {
    // The delete cascades the root's scans, findings and fixes away, so the
    // route refuses it — and now the menu item says so first.
    await mockTerraformRoots(page, [
      { ...MOCK_TERRAFORM_ROOT, latest_scan_status: "running" },
    ])

    await page.goto(`/infrastructure/${MOCK_REPO.id}/terraform`)
    await page.getByRole("button", { name: "More actions" }).first().click()

    await expect(page.getByRole("menuitem", { name: "Remove" })).toBeDisabled()
  })

  test("a spent analysis allowance greys the scan in the 402's own words", async ({
    page,
  }) => {
    const spent =
      "You've used all 100 analyses included in the Free plan this month."
    await mockBilling(page, undefined, undefined, undefined, {
      quotas: quotaSpent("analyses", spent),
    })
    await mockTerraformRoots(page)

    await page.goto(`/infrastructure/${MOCK_REPO.id}/terraform`)

    const scan = page.getByRole("button", { name: "Scan now" }).first()
    await expect(scan).toBeDisabled()
    await reasonFor(scan)
    await expect(page.getByText(spent)).toBeVisible()
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

  // ── What a busy target refuses ───────────────────────────────────────────
  //
  // The rule these cover lives in `lib/engine-actions.ts` and, identically, in
  // `services/state_machines/engine_target.py`. Here they check the wiring:
  // that the card reads its own scan and fix state, and says why rather than
  // offering an action the API would answer 409 to.

  test("a running scan disables every action on the root", async ({ page }) => {
    await mockTerraformRoots(page, [
      { ...MOCK_TERRAFORM_ROOT, latest_scan_status: "running" },
    ])

    await page.goto(`/infrastructure/${MOCK_REPO.id}/terraform`)

    for (const name of [/Scan/, /Generate fixes/, /Create PR|Update PR/]) {
      await expect(page.getByRole("button", { name }).first()).toBeDisabled()
    }
    // And the button says so rather than leaving the user to guess.
    await expect(page.getByRole("button", { name: /Scanning/ })).toBeVisible()
  })

  test("a fix being generated blocks the scan and the PR, not more fixes", async ({
    page,
  }) => {
    await mockTerraformRoots(page, [MOCK_TERRAFORM_ROOT], {
      fixes: [{ ...MOCK_TERRAFORM_FIX, status: "generating" }],
    })

    await page.goto(`/infrastructure/${MOCK_REPO.id}/terraform`)

    await expect(
      page.getByRole("button", { name: "Scan now" }).first(),
    ).toBeDisabled()
    await expect(
      page.getByRole("button", { name: /Create PR|Update PR/ }).first(),
    ).toBeDisabled()
    // Writing a fix for another file while this one is in flight is ordinary
    // work, so generation stays available.
    await expect(
      page.getByRole("button", { name: /Generating/ }).first(),
    ).toBeEnabled()
  })

  test("a disabled root explains why its actions are off", async ({ page }) => {
    await mockTerraformRoots(page, [{ ...MOCK_TERRAFORM_ROOT, enabled: false }])

    await page.goto(`/infrastructure/${MOCK_REPO.id}/terraform`)

    const scan = page.getByRole("button", { name: "Scan now" }).first()
    await expect(scan).toBeDisabled()
    // The tooltip hangs off a focusable wrapper, since a disabled button
    // swallows pointer events.
    await scan.locator("..").hover()
    await expect(
      page.getByText("Enable this terraform root first"),
    ).toBeVisible()
  })

  test("removing a root asks before it deletes", async ({ page }) => {
    await mockTerraformRoots(page)

    await page.goto(`/infrastructure/${MOCK_REPO.id}/terraform`)

    await page.getByRole("button", { name: "More actions" }).first().click()
    await page.getByRole("menuitem", { name: "Remove" }).click()

    const dialog = page.getByRole("alertdialog")
    await expect(dialog).toContainText("deploy/terraform")
    const request = page.waitForRequest(
      (r) =>
        r.url().includes(`/terraform/roots/${MOCK_TERRAFORM_ROOT.id}`) &&
        r.method() === "DELETE",
    )
    await dialog.getByRole("button", { name: "Remove" }).click()
    await request
  })
})
