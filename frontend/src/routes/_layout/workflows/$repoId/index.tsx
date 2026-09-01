import { createFileRoute, redirect } from "@tanstack/react-router"

export const Route = createFileRoute("/_layout/workflows/$repoId/")({
  beforeLoad: ({ params }) => {
    throw redirect({
      to: "/workflows/$repoId/static-analysis",
      params: { repoId: params.repoId },
    })
  },
})
