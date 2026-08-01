import { createFileRoute, redirect } from "@tanstack/react-router"

// Badges consolidated onto one page with a tab per engine. This route stays
// behind so bookmarks and links in older PR bodies keep working.
export const Route = createFileRoute("/_layout/docker/badges")({
  beforeLoad: () => {
    throw redirect({ to: "/badges/docker" })
  },
})
