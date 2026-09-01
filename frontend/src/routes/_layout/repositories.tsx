import { createFileRoute, Outlet } from "@tanstack/react-router"

/**
 * Where the CI-workflow engine's pages used to live.
 *
 * They moved to `/workflows` so the URL agrees with the name the sidebar, the
 * dashboard and the page heading already used. The old paths are kept as
 * redirects rather than deleted: every fix PR body and PR comment GreenSecOps
 * has ever opened links to `{FRONTEND_HOST}/repositories/...`, and those links
 * live in other people's repositories where nothing can rewrite them.
 *
 * Only a passthrough itself — the two children below do the redirecting, so
 * that `/repositories/{id}/pull-requests` reaches the tab it names instead of
 * being swallowed by a redirect on the parent.
 */
export const Route = createFileRoute("/_layout/repositories")({
  component: Outlet,
})
