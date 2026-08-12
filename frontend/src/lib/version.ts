/**
 * What this bundle is, and where it was built to run.
 *
 * The version is baked in by vite.config.ts from frontend/package.json, which
 * scripts/bump_version.py writes from the root VERSION file — so it travels
 * with the source and needs no build-time plumbing. The environment and commit
 * do come from the build, because the same source is published to staging and
 * production.
 */

/** The released version, e.g. "0.11.0". Never empty — it is compiled in. */
export const APP_VERSION: string = __APP_VERSION__

/**
 * Which deployment this bundle targets.
 *
 * Defaults to "local" rather than "production": an unset variable must never
 * read as production, or a misconfigured build would hide its own staging
 * badge — which is precisely when you most need to see it.
 */
export const APP_ENVIRONMENT: string =
  import.meta.env.VITE_APP_ENVIRONMENT || "local"

/**
 * Commit the bundle was built from, supplied outside production so a staging
 * build is bisectable.
 *
 * Truncated here rather than by each caller: the Cloudflare build passes
 * `github.sha` (40 characters, because workflow expressions cannot slice), the
 * AWS path passes an already-short image tag, and a footer wants neither of
 * those to decide how it looks.
 */
export const APP_COMMIT: string = (import.meta.env.VITE_APP_COMMIT || "").slice(
  0,
  7,
)

export const IS_PRODUCTION = APP_ENVIRONMENT === "production"

/**
 * The version as shown to a human.
 *
 * Production gets a bare "v0.11.0". Everywhere else gets the commit appended,
 * because outside production the version alone is misleading: staging runs
 * whatever is on main, which is almost always ahead of the last release, so two
 * different staging builds would otherwise be indistinguishable — and telling
 * them apart is the entire reason to look at a footer.
 *
 * "+sha" is semver build metadata, so this stays a valid version string.
 */
export function displayVersion(): string {
  if (IS_PRODUCTION || !APP_COMMIT) {
    return `v${APP_VERSION}`
  }
  return `v${APP_VERSION}+${APP_COMMIT}`
}
