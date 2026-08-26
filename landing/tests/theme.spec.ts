import { expect, test } from "@playwright/test"

const PAGES = [
  "/index.html",
  "/features.html",
  "/workflows.html",
  "/terraform.html",
  "/ansible.html",
  "/docker.html",
  "/pricing.html",
  "/privacy.html",
  "/terms.html",
]

test.describe("theme toggle", () => {
  test("defaults to system preference with no stored choice", async ({
    page,
  }) => {
    await page.emulateMedia({ colorScheme: "dark" })
    await page.goto("/index.html")
    await expect(page.locator("html")).toHaveClass("dark")
  })

  test("toggling to dark updates html class and persists across reload", async ({
    page,
  }) => {
    await page.goto("/index.html")
    await expect(page.locator("html")).toHaveClass("light")

    await page.click(".theme-toggle")
    await page.click('.theme-menu__item[data-theme="dark"]')
    await expect(page.locator("html")).toHaveClass("dark")

    await page.reload()
    await expect(page.locator("html")).toHaveClass("dark")
  })

  test("toggling back to light updates html class and persists", async ({
    page,
  }) => {
    await page.goto("/index.html")
    await page.click(".theme-toggle")
    await page.click('.theme-menu__item[data-theme="dark"]')
    await expect(page.locator("html")).toHaveClass("dark")

    await page.click(".theme-toggle")
    await page.click('.theme-menu__item[data-theme="light"]')
    await expect(page.locator("html")).toHaveClass("light")

    await page.reload()
    await expect(page.locator("html")).toHaveClass("light")
  })

  test("system option follows OS preference live", async ({ page }) => {
    await page.goto("/index.html")
    await page.click(".theme-toggle")
    await page.click('.theme-menu__item[data-theme="system"]')
    await expect(page.locator("html")).toHaveClass("light")

    await page.emulateMedia({ colorScheme: "dark" })
    await expect(page.locator("html")).toHaveClass("dark")
  })

  for (const path of PAGES) {
    test(`toggle works on ${path}`, async ({ page }) => {
      await page.goto(path)
      await expect(page.locator("html")).toHaveClass("light")

      await page.click(".theme-toggle")
      await page.click('.theme-menu__item[data-theme="dark"]')
      await expect(page.locator("html")).toHaveClass("dark")

      const background = await page.evaluate(
        () => getComputedStyle(document.body).backgroundColor,
      )
      expect(background).not.toBe("oklch(0.985 0.002 152)")
    })
  }
})
