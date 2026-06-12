import { createFileRoute } from "@tanstack/react-router"
import { z } from "zod"

// GitHub redirects the OAuth popup here with `?code=&state=` (or `?error=`).
// The opener window (see GitHubOAuthButton) polls this popup's URL, reads those
// params, exchanges the code via the backend, and closes the popup. This route
// must therefore stay a passive landing page: it must NOT redirect or exchange
// the code itself, otherwise the params would be lost before the opener reads them.
const searchSchema = z.object({
  code: z.string().optional(),
  state: z.string().optional(),
  error: z.string().optional(),
  error_description: z.string().optional(),
})

export const Route = createFileRoute("/auth/github/callback")({
  validateSearch: searchSchema,
  component: GitHubOAuthCallback,
  head: () => ({
    meta: [{ title: "Signing in - GreenSecOps" }],
  }),
})

function GitHubOAuthCallback() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <p className="text-muted-foreground text-sm">Signing in with GitHub…</p>
    </div>
  )
}
