import { createFileRoute, redirect } from "@tanstack/react-router"

// Docker analysis moved out of Infrastructure into its own top-level section.
// This route stays behind so bookmarks and older PR links keep working.
export const Route = createFileRoute("/_layout/infrastructure/$repoId/docker")({
  beforeLoad: ({ params }) => {
    throw redirect({
      to: "/docker/$repoId/analysis",
      params: { repoId: params.repoId },
    })
  },
})
