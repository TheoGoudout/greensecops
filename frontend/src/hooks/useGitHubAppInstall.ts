import { useQueryClient } from "@tanstack/react-query"
import { useCallback } from "react"

const GITHUB_APP_NAME = import.meta.env.VITE_GITHUB_APP_NAME as string

export function useGitHubAppInstall() {
  const queryClient = useQueryClient()

  const openInstallPopup = useCallback(() => {
    const url = `https://github.com/apps/${GITHUB_APP_NAME}/installations/new`
    const popup = window.open(
      url,
      "github-app-install",
      "popup,width=1024,height=768",
    )
    if (!popup) return
    const timer = setInterval(() => {
      if (popup.closed) {
        clearInterval(timer)
        queryClient.invalidateQueries({ queryKey: ["installations"] })
      }
    }, 500)
  }, [queryClient])

  return { openInstallPopup }
}
