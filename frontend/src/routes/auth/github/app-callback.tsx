import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { CheckCircle, XCircle } from "lucide-react"
import { useEffect } from "react"
import { z } from "zod"

const searchSchema = z.object({
  installation_id: z.coerce.number().optional(),
  setup_action: z.enum(["install", "update", "delete"]).optional(),
  error: z.string().optional(),
  error_description: z.string().optional(),
})

export const Route = createFileRoute("/auth/github/app-callback")({
  validateSearch: searchSchema,
  component: GitHubAppCallback,
  head: () => ({
    meta: [{ title: "GitHub App Setup - GreenSecOps" }],
  }),
})

function GitHubAppCallback() {
  const { installation_id, setup_action, error } = Route.useSearch()
  const navigate = useNavigate()

  const isSuccess = !error && !!installation_id

  useEffect(() => {
    const timer = setTimeout(() => {
      navigate({ to: "/repositories" })
    }, 2500)
    return () => clearTimeout(timer)
  }, [navigate])

  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="flex flex-col items-center gap-4 text-center max-w-sm">
        {isSuccess ? (
          <>
            <CheckCircle className="h-12 w-12 text-green-500" />
            <h2 className="text-lg font-semibold">GitHub App installed</h2>
            <p className="text-sm text-muted-foreground">
              {setup_action === "update"
                ? "Installation updated successfully."
                : "Installation complete. Your repositories will appear shortly."}
            </p>
          </>
        ) : (
          <>
            <XCircle className="h-12 w-12 text-destructive" />
            <h2 className="text-lg font-semibold">Installation failed</h2>
            <p className="text-sm text-muted-foreground">
              {error ?? "Something went wrong. Please try again."}
            </p>
          </>
        )}
        <p className="text-xs text-muted-foreground">
          Redirecting to Repositories…
        </p>
      </div>
    </div>
  )
}
