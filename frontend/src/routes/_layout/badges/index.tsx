import { createFileRoute, redirect } from "@tanstack/react-router"

export const Route = createFileRoute("/_layout/badges/")({
  beforeLoad: () => {
    throw redirect({ to: "/badges/repositories" })
  },
})
