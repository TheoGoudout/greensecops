import { createFileRoute, redirect } from "@tanstack/react-router"

/**
 * Everything under the old `/repositories/...` prefix, forwarded verbatim.
 *
 * A splat rather than one route per tab so a path this app no longer knows —
 * an old tab name, a link built by hand — still lands somewhere under
 * `/workflows` and gets a 404 from the router there, rather than silently
 * dropping the reader on the repository list.
 */
export const Route = createFileRoute("/_layout/repositories/$")({
  beforeLoad: ({ params }) => {
    throw redirect({
      href: `/workflows/${params._splat ?? ""}`,
      replace: true,
    })
  },
})
