import { createFileRoute, redirect, useNavigate } from "@tanstack/react-router"
import { useEffect } from "react"
import { z } from "zod"
import { AuthService } from "@/client"

const searchSchema = z.object({
  code: z.string(),
  state: z.string().optional(),
  error: z.string().optional(),
  error_description: z.string().optional(),
})

export const Route = createFileRoute("/auth/github/callback")({
  validateSearch: searchSchema,
  beforeLoad: async ({ search }) => {
    if (search.error) {
      throw redirect({ to: "/login" })
    }
    try {
      const token = await AuthService.githubCallback({
        code: search.code,
        state: search.state,
      })
      localStorage.setItem("access_token", token.access_token)
      throw redirect({ to: "/" })
    } catch (err) {
      const isRedirect =
        err instanceof Error && err.message.includes("redirect")
      if (isRedirect) throw err
      // Re-throw TanStack Router redirect objects
      if (err && typeof err === "object" && "to" in err) throw err
      throw redirect({ to: "/login" })
    }
  },
  component: GitHubOAuthCallback,
  head: () => ({
    meta: [{ title: "Signing in - GreenSecOps" }],
  }),
})

function GitHubOAuthCallback() {
  const navigate = useNavigate()
  useEffect(() => {
    navigate({ to: "/" })
  }, [navigate])
  return (
    <div className="flex min-h-screen items-center justify-center">
      <p className="text-muted-foreground text-sm">Signing in with GitHub…</p>
    </div>
  )
}
