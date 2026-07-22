import { expect, test } from "@playwright/test"

test.describe("hero fix animation", () => {
  test("plays through ? -> D -> A+++ and rests on the fixed state", async ({
    page,
  }) => {
    await page.goto("/index.html")

    const grade = page.locator(".hero__result-grade")
    const sub = page.locator(".hero__result-sub")
    const check = page.locator(".hero__result-check")

    // Auto-plays on scroll-into-view (the card is at the top of the page) and
    // settles on the compliant workflow at A+++ with no issues.
    await expect(grade).toHaveText("A+++", { timeout: 20000 })
    await expect(grade).toHaveClass(/grade-badge--aaa/)
    await expect(sub).toContainText("0 critical issues")
    await expect(check).toBeVisible()
  })

  test("replay restarts from the analyzing state and highlights each error", async ({
    page,
  }) => {
    await page.goto("/index.html")
    const grade = page.locator(".hero__result-grade")

    // Wait until the auto-play is underway (reached the flagged grade), then
    // replay force-restarts it from the top regardless of the current phase.
    await expect(grade).toHaveText("D", { timeout: 20000 })

    await page.click(".hero__replay")

    // Restarts immediately on the "analyzing" grade.
    await expect(grade).toHaveText("?")
    await expect(grade).toHaveClass(/grade-badge--unknown/)

    // Flips to D and highlights all four flagged lines one by one.
    await expect(grade).toHaveText("D", { timeout: 5000 })
    await expect(
      page.locator(".wf-anim__code .tw-ln--flag.is-flag-on"),
    ).toHaveCount(4, { timeout: 5000 })

    // Then fixes everything and returns to A+++.
    await expect(grade).toHaveText("A+++", { timeout: 20000 })
  })

  test("prefers-reduced-motion rests on the fixed state with no motion", async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion: "reduce" })
    await page.goto("/index.html")

    const grade = page.locator(".hero__result-grade")
    await expect(grade).toHaveText("A+++")
    await expect(grade).toHaveClass(/grade-badge--aaa/)

    // The flagged phase never runs.
    await expect(
      page.locator(".wf-anim__code .tw-ln--flag.is-flag-on"),
    ).toHaveCount(0)
  })
})
