import { createFileRoute, redirect } from "@tanstack/react-router"

export const Route = createFileRoute("/_layout/docker/$repoId/")({
  beforeLoad: ({ params }) => {
    throw redirect({
      to: "/docker/$repoId/analysis",
      params: { repoId: params.repoId },
    })
  },
})
