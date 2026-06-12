import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { CheckCircle, Loader2, XCircle } from "lucide-react"
import { useEffect, useState } from "react"
import { z } from "zod"
import { InstallationsService } from "@/client"

const searchSchema = z.object({
  installation_id: z.coerce.number().optional(),
  setup_action: z.enum(["install", "update", "delete"]).optional(),
  code: z.string().optional(),
  state: z.string().optional(),
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

type SyncState = "idle" | "syncing" | "done" | "error"

function GitHubAppCallback() {
  const { installation_id, setup_action, code, error } = Route.useSearch()
  const navigate = useNavigate()

  const initiallySuccessful = !error && !!installation_id
  const shouldSync =
    initiallySuccessful &&
    !!code &&
    (setup_action === "install" || setup_action === "update")

  const [syncState, setSyncState] = useState<SyncState>(
    shouldSync ? "syncing" : initiallySuccessful ? "done" : "error",
  )

  // Exchange the install-time OAuth code for the user's installations so that
  // ownership is linked and repositories are queued for sync.
  useEffect(() => {
    if (!shouldSync || !code) return
    let cancelled = false
    InstallationsService.syncInstallations({ requestBody: { code } })
      .then(() => {
        if (!cancelled) setSyncState("done")
      })
      .catch(() => {
        if (!cancelled) setSyncState("error")
      })
    return () => {
      cancelled = true
    }
  }, [shouldSync, code])

  // Redirect once we are no longer actively syncing.
  useEffect(() => {
    if (syncState === "syncing") return
    const timer = setTimeout(() => {
      navigate({ to: "/repositories" })
    }, 2500)
    return () => clearTimeout(timer)
  }, [navigate, syncState])

  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="flex flex-col items-center gap-4 text-center max-w-sm">
        {syncState === "syncing" ? (
          <>
            <Loader2 className="h-12 w-12 animate-spin text-muted-foreground" />
            <h2 className="text-lg font-semibold">Finishing setup…</h2>
            <p className="text-sm text-muted-foreground">
              Syncing your repositories from GitHub.
            </p>
          </>
        ) : syncState === "done" ? (
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
        {syncState !== "syncing" && (
          <p className="text-xs text-muted-foreground">
            Redirecting to Repositories…
          </p>
        )}
      </div>
    </div>
  )
}
