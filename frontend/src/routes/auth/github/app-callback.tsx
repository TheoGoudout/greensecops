import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { CheckCircle, Loader2, XCircle } from "lucide-react"
import { useEffect, useState } from "react"
import { z } from "zod"
import { InstallationsService } from "@/client"
import { isLoggedIn } from "@/hooks/useAuth"

export const PENDING_INSTALLATION_KEY = "pending_installation"

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
    // Must be authenticated — /installations/sync is a protected endpoint.
    // Store params so login page can redirect back to complete the sync.
    if (!isLoggedIn()) {
      sessionStorage.setItem(
        PENDING_INSTALLATION_KEY,
        JSON.stringify({ code, installation_id, setup_action }),
      )
      navigate({ to: "/login" })
      return
    }
    let cancelled = false
    InstallationsService.syncInstallations({ requestBody: { code } })
      .then(() => {
        if (cancelled) return
        setSyncState("done")
        window.opener?.postMessage(
          { type: "github-app-installed" },
          window.location.origin,
        )
      })
      .catch(() => {
        if (cancelled) return
        setSyncState("error")
        window.opener?.postMessage(
          { type: "github-app-install-failed" },
          window.location.origin,
        )
      })
    return () => {
      cancelled = true
    }
  }, [shouldSync, code, installation_id, setup_action, navigate])

  // Close popup or redirect once we are no longer actively syncing.
  useEffect(() => {
    if (syncState === "syncing") return
    if (window.opener) {
      const timer = setTimeout(() => window.close(), 1500)
      return () => clearTimeout(timer)
    }
    const timer = setTimeout(() => {
      navigate({ to: "/workflows" })
    }, 2500)
    return () => clearTimeout(timer)
  }, [navigate, syncState])

  const doneTitle =
    setup_action === "delete"
      ? "GitHub App uninstalled"
      : "GitHub App installed"
  const doneBody =
    setup_action === "delete"
      ? "The app has been removed from your account."
      : setup_action === "update"
        ? "Installation updated successfully."
        : "Installation complete. Your repositories will appear shortly."

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
            <h2 className="text-lg font-semibold">{doneTitle}</h2>
            <p className="text-sm text-muted-foreground">{doneBody}</p>
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
