import { useQueryClient } from "@tanstack/react-query"
import { useCallback, useEffect } from "react"

const GITHUB_APP_NAME = import.meta.env.VITE_GITHUB_APP_NAME as string

function invalidateInstallationCaches(
  queryClient: ReturnType<typeof useQueryClient>,
) {
  queryClient.invalidateQueries({ queryKey: ["installations"] })
  queryClient.invalidateQueries({ queryKey: ["repositories"] })
}

export function useGitHubAppInstall() {
  const queryClient = useQueryClient()

  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin) return
      if (
        event.data?.type !== "github-app-installed" &&
        event.data?.type !== "github-app-install-failed"
      )
        return
      invalidateInstallationCaches(queryClient)
      window.dispatchEvent(new CustomEvent("sse:reconnect"))
    }
    window.addEventListener("message", handleMessage)
    return () => window.removeEventListener("message", handleMessage)
  }, [queryClient])

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
        invalidateInstallationCaches(queryClient)
      }
    }, 500)
  }, [queryClient])

  return { openInstallPopup }
}
