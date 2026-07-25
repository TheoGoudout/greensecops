import { createFileRoute, redirect } from "@tanstack/react-router"

export const Route = createFileRoute("/_layout/infrastructure/$repoId/")({
  beforeLoad: ({ params }) => {
    throw redirect({
      to: "/infrastructure/$repoId/terraform",
      params: { repoId: params.repoId },
    })
  },
})
