import { useGitHubLogin } from "@react-oauth/github"
import { useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { FaGithub } from "react-icons/fa"
import { AuthService } from "@/client"
import { Button } from "@/components/ui/button"
import useCustomToast from "@/hooks/useCustomToast"

export function GitHubOAuthButton() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showErrorToast } = useCustomToast()

  const { initiateGitHubLogin, isLoading } = useGitHubLogin({
    clientId: import.meta.env.VITE_GITHUB_CLIENT_ID,
    // Must match the GitHub OAuth App callback URL and the backend's
    // GITHUB_OAUTH_REDIRECT_URI (GitHub validates the redirect_uri on exchange).
    redirectUri: `${window.location.origin}/auth/github/callback`,
    scope: "read:user user:email",
    onSuccess: async ({ code, state }) => {
      try {
        const token = await AuthService.githubCallback({ code, state })
        localStorage.setItem("access_token", token.access_token)
        await queryClient.invalidateQueries({ queryKey: ["currentUser"] })
        navigate({ to: "/" })
      } catch {
        showErrorToast("GitHub sign in failed. Please try again.")
      }
    },
    onError: (error) => {
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
