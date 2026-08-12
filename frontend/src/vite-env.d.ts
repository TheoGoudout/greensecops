/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL: string
  readonly VITE_GREENSECOPS_PUBLIC_URL: string
  readonly VITE_GITHUB_OAUTH_CLIENT_ID: string
  /**
   * Which deployment this bundle was built for: "production", "staging",
   * "preview" or "local". Drives the footer's environment badge, so an
   * unset value has to read as "not production" rather than as production.
   */
  readonly VITE_APP_ENVIRONMENT: string
  /** Short commit the bundle was built from. Shown outside production. */
  readonly VITE_APP_COMMIT: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

/**
 * The version from frontend/package.json, injected by vite.config.ts's
 * `define`. Not a VITE_ variable: it travels with the source, because
 * scripts/bump_version.py writes package.json from the root VERSION file.
 */
declare const __APP_VERSION__: string
