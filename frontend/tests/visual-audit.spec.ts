import fs from "node:fs"
import path from "node:path"
import { expect, type Page, test } from "@playwright/test"

test.setTimeout(180000)

const REPO_ID = "8f5175a1-5631-4dd9-b784-f865ee0913b7"
const ANALYSIS_ID = "cdc25d5e-6570-4d64-a573-88ec0e915868"
const FIX_ID = "860814f2-1fc6-4042-9ba8-d1a6f292a819"

const VIEWPORTS = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "mobile", width: 390, height: 844 },
]

type PageConfig = {
  name: string
  route: string
  auth: boolean
  waitFor?: string | null
  skipSkeletonWait?: boolean
}

const PAGES: PageConfig[] = [
  // Auth pages — fresh unauthenticated context; wait for form element to confirm router resolved
  {
    name: "login",
    route: "/login",
    auth: false,
    waitFor: '[data-testid="email-input"]',
  },
  {
    name: "signup",
    route: "/signup",
    auth: false,
    waitFor: '[data-testid="email-input"]',
  },
  {
    name: "recover-password",
    route: "/recover-password",
    auth: false,
    waitFor: '[data-testid="email-input"]',
  },
  // reset-password requires ?token= to show the form (beforeLoad redirects otherwise)
  {
    name: "reset-password",
    route: "/reset-password?token=test-token-for-screenshot",
    auth: false,
    waitFor: '[data-testid="new-password-input"]',
  },

  // App pages (login required)
  { name: "dashboard", route: "/dashboard", auth: true },
  { name: "repositories", route: "/repositories", auth: true },
  { name: "repository-detail", route: `/repositories/${REPO_ID}`, auth: true },
  {
    name: "repository-static-analysis",
    route: `/repositories/${REPO_ID}/static-analysis`,
    auth: true,
  },
  {
    name: "repository-telemetry",
    route: `/repositories/${REPO_ID}/telemetry`,
    auth: true,
  },
  {
    name: "repository-pull-requests",
    route: `/repositories/${REPO_ID}/pull-requests`,
    auth: true,
  },
  { name: "docker", route: "/docker", auth: true },
  { name: "docker-analysis", route: `/docker/${REPO_ID}/analysis`, auth: true },
  {
    name: "docker-pull-requests",
    route: `/docker/${REPO_ID}/pull-requests`,
    auth: true,
  },
  { name: "docker-scans", route: `/docker/${REPO_ID}/scans`, auth: true },
  { name: "docker-badges", route: "/docker/badges", auth: true },
  { name: "analysis-detail", route: `/analyses/${ANALYSIS_ID}`, auth: true },
  { name: "fix-detail", route: `/fixes/${FIX_ID}`, auth: true },
  { name: "rules", route: "/rules", auth: true },
  { name: "badges", route: "/badges", auth: true },
  { name: "billing", route: "/billing", auth: true },
  // settings: /users/me returns 404 (stale token) → useAuth never resolves → skeletons never clear
  { name: "settings", route: "/settings", auth: true, skipSkeletonWait: true },
  { name: "admin", route: "/admin", auth: true },
]

const screenshotsDir = path.join(import.meta.dirname, "../screenshots")

async function waitForSkeletonsGone(page: Page) {
  await page
    .waitForFunction(
      () => document.querySelectorAll('[data-slot="skeleton"]').length === 0,
      { timeout: 15000 },
    )
    .catch(() => {
      // skeletons still present after timeout — data may be empty or loading failed
    })
}

async function waitForContent(page: Page, config: PageConfig) {
  await page.waitForLoadState("load")
  if (config.waitFor) {
    await page.waitForSelector(config.waitFor, { timeout: 15000 })
  } else {
    await Promise.race([
      page.waitForLoadState("networkidle"),
      new Promise((resolve) => setTimeout(resolve, 5000)),
    ])
    if (!config.skipSkeletonWait) {
      await waitForSkeletonsGone(page)
    }
  }
}

async function checkOverflow(page: Page, pageName: string) {
  const hasHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  )
  expect(
    hasHorizontalOverflow,
    `Horizontal overflow detected on ${pageName}`,
  ).toBe(false)
}

async function takePageScreenshot(
  page: Page,
  pageName: string,
  viewportName: string,
) {
  const dir = path.join(screenshotsDir, viewportName)
  fs.mkdirSync(dir, { recursive: true })
  const filepath = path.join(dir, `${pageName}.png`)
  await page.screenshot({ path: filepath, fullPage: true })
  return filepath
}

for (const viewport of VIEWPORTS) {
  test.describe(`Visual audit — ${viewport.name} (${viewport.width}x${viewport.height})`, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } })

    for (const pageConfig of PAGES) {
      test(`${pageConfig.name}`, async ({ page, browser }) => {
        if (!pageConfig.auth) {
          const ctx = await browser.newContext({
            viewport: { width: viewport.width, height: viewport.height },
            storageState: { cookies: [], origins: [] },
          })
          const freshPage = await ctx.newPage()
          await freshPage.goto(pageConfig.route)
          await waitForContent(freshPage, pageConfig)
          await checkOverflow(freshPage, pageConfig.name)
          const filepath = await takePageScreenshot(
            freshPage,
            pageConfig.name,
            viewport.name,
          )
          console.log(`Screenshot saved: ${filepath}`)
          await ctx.close()
        } else {
          await page.goto(pageConfig.route)
          await waitForContent(page, pageConfig)
          await checkOverflow(page, pageConfig.name)
          const filepath = await takePageScreenshot(
            page,
            pageConfig.name,
            viewport.name,
          )
          console.log(`Screenshot saved: ${filepath}`)
        }
      })
    }
  })
}
