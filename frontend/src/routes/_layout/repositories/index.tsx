import { createFileRoute, redirect } from "@tanstack/react-router"

export const Route = createFileRoute("/_layout/repositories/")({
  beforeLoad: () => {
    throw redirect({ to: "/workflows", replace: true })
  },
})
