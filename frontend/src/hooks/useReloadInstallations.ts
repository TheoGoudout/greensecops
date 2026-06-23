import { OAuthError, OAuthErrorCode, useGitHubLogin } from "@react-oauth/github"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { InstallationsService } from "@/client"
import useCustomToast from "@/hooks/useCustomToast"

const REDIRECT_URI = `${window.location.origin}/auth/github/callback`

export function useReloadInstallations() {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const syncMutation = useMutation({
    mutationFn: (code: string) =>
      InstallationsService.syncInstallations({
        requestBody: { code, redirect_uri: REDIRECT_URI },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["installations"] })
      showSuccessToast("Installations reloaded successfully.")
    },
    onError: () => {
      showErrorToast("Failed to reload installations. Please try again.")
    },
  })

  const { initiateGitHubLogin, isLoading: isOAuthLoading } = useGitHubLogin({
    clientId: import.meta.env.VITE_GITHUB_OAUTH_CLIENT_ID,
    redirectUri: REDIRECT_URI,
    scope: "read:user user:email",
    onSuccess: ({ code }) => {
      syncMutation.mutate(code)
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
      }
      showErrorToast(
        error.message || "Failed to reload installations. Please try again.",
      )
    },
  })

  return {
    reloadInstallations: initiateGitHubLogin,
    isLoading: isOAuthLoading || syncMutation.isPending,
  }
}
