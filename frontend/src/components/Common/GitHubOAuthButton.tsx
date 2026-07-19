import { OAuthError, OAuthErrorCode, useGitHubLogin } from "@react-oauth/github"
import { useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { FaGithub } from "react-icons/fa"
import { AuthService } from "@/client"
import { Button } from "@/components/ui/button"
import { showErrorToast } from "@/utils"

export function GitHubOAuthButton() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { initiateGitHubLogin, isLoading } = useGitHubLogin({
    clientId: import.meta.env.VITE_GITHUB_OAUTH_CLIENT_ID,
    // Must match the GitHub OAuth App "Authorization callback URL".
    // Set that URL in your GitHub OAuth App settings to this frontend route.
    redirectUri: `${window.location.origin}/auth/github/callback`,
    scope: "read:user user:email",
    onSuccess: async ({ code }) => {
      try {
        const token = await AuthService.githubCallback({
          formData: {
            code,
            client_id: import.meta.env.VITE_GITHUB_OAUTH_CLIENT_ID,
          },
        })
        localStorage.setItem("access_token", token.access_token)
        await queryClient.invalidateQueries({ queryKey: ["currentUser"] })
        const pending = sessionStorage.getItem("pending_installation")
        if (pending) {
          sessionStorage.removeItem("pending_installation")
          try {
            const params = JSON.parse(pending) as Record<string, unknown>
            navigate({ to: "/auth/github/app-callback", search: params })
            return
          } catch {
            // malformed entry — fall through to default redirect
          }
        }
        navigate({ to: "/" })
      } catch {
        showErrorToast("GitHub sign in failed. Please try again.")
      }
    },
    onError: (error) => {
      if (OAuthError.isOAuthError(error)) {
        if (error.code === OAuthErrorCode.POPUP_CLOSED) return
        if (error.code === OAuthErrorCode.POPUP_BLOCKED) {
          showErrorToast(
            "Popup blocked. Allow popups for this site and try again.",
          )
          return
        }
        if (error.code === OAuthErrorCode.STATE_MISMATCH) {
          showErrorToast(
            "Sign in failed: security check failed. Please try again.",
          )
          return
        }
      }
      // Surface the provider's error_description (e.g. "The user denied access")
      // when the error is a plain Error thrown from the OAuth callback URL.
      showErrorToast(
        error.message || "GitHub sign in failed. Please try again.",
      )
    },
  })

  return (
    <Button
      type="button"
      variant="outline"
      className="w-full"
      onClick={initiateGitHubLogin}
      disabled={isLoading}
      data-testid="github-oauth-btn"
    >
      <FaGithub className="mr-2 h-4 w-4" />
      {isLoading ? "Connecting to GitHub…" : "Continue with GitHub"}
    </Button>
  )
}
