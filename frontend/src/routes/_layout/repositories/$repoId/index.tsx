import { createFileRoute, redirect } from "@tanstack/react-router"

export const Route = createFileRoute("/_layout/repositories/$repoId/")({
  beforeLoad: ({ params }) => {
    throw redirect({
      to: "/repositories/$repoId/analyses",
      params: { repoId: params.repoId },
    })
  },
})
