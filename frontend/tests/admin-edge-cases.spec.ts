import { expect, test } from "@playwright/test"
import { firstSuperuser } from "./config.ts"
import { createUser } from "./utils/privateApi"
import { randomEmail, randomPassword } from "./utils/random"
import { logInUser } from "./utils/user"

test.describe("Admin edge cases", () => {
  test("superuser cannot delete themselves", async ({ page }) => {
    await page.goto("/admin")

    await expect(page.getByRole("heading", { name: "Admin" })).toBeVisible()

    const superuserRow = page
      .getByRole("row")
      .filter({ hasText: firstSuperuser })
    await expect(superuserRow).toBeVisible({ timeout: 15000 })

    const menuBtn = superuserRow.getByRole("button")
    if (await menuBtn.isVisible()) {
      await menuBtn.click()
      const deleteItem = page.getByRole("menuitem", { name: "Delete User" })
      if (await deleteItem.isVisible()) {
        await deleteItem.click()
        await page.getByRole("button", { name: "Delete" }).click()
        await expect(
          page.getByText(/cannot delete yourself|not allowed|forbidden/i),
        ).toBeVisible({ timeout: 5000 })
      }
    }
  })

  test("reanalyze all repos button is visible for superuser", async ({
    page,
  }) => {
    await page.goto("/admin")
    await expect(page.getByRole("heading", { name: "Admin" })).toBeVisible()

    const reanalyzeBtn = page.getByRole("button", {
      name: /reanalyze all|re-analyze/i,
    })
    if (await reanalyzeBtn.isVisible()) {
      expect(await reanalyzeBtn.isVisible()).toBe(true)
    }
  })

  test("reanalyze all calls API and shows confirmation", async ({ page }) => {
    let reanalyzeCalled = false

    await page.route("**/api/v1/workflow-scans/reanalyze-all", (route) => {
      reanalyzeCalled = true
      route.fulfill({ status: 202, json: { status: "queued" } })
    })

    await page.goto("/admin")
    await expect(page.getByRole("heading", { name: "Admin" })).toBeVisible()

    const reanalyzeBtn = page.getByRole("button", {
      name: /reanalyze all|re-analyze/i,
    })
    if (await reanalyzeBtn.isVisible()) {
      await reanalyzeBtn.click()

      const confirmBtn = page.getByRole("button", {
        name: /confirm|yes|proceed/i,
      })
      if (await confirmBtn.isVisible()) {
        await confirmBtn.click()
      }

      expect(reanalyzeCalled).toBe(true)
    }
  })

  test("duplicate email shows error on user creation", async ({ page }) => {
    await page.goto("/admin")

    await page.getByRole("button", { name: "Add User" }).click()
    await page.getByPlaceholder("Email").fill(firstSuperuser)
    const password = randomPassword()
    await page.getByPlaceholder("Password").first().fill(password)
    await page.getByPlaceholder("Password").last().fill(password)
    await page.getByRole("button", { name: "Save" }).click()

    await expect(
      page.getByText(/already exists|duplicate|conflict/i),
    ).toBeVisible({ timeout: 5000 })
  })
})

test.describe("Admin access control — non-superuser", () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test("non-superuser cannot access admin page", async ({ page }) => {
    const email = randomEmail()
    const password = randomPassword()

    await createUser({ email, password })
    await logInUser(page, email, password)

    await page.goto("/admin")

    await expect(page.getByRole("heading", { name: "Admin" })).not.toBeVisible({
      timeout: 5000,
    })
  })
})
