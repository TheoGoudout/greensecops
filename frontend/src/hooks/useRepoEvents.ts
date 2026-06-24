import { useQueryClient } from "@tanstack/react-query"
import { useCallback } from "react"
import { type SSEEventData, useSSE } from "./useSSE"

/**
 * Subscribes to SSE and invalidates TanStack Query caches when the server
 * emits events for repos, analyses, fixes, PRs, or installations.
 *
 * Mount once at the authenticated layout level — covers all child routes.
 */
export function useRepoEvents(): void {
  const queryClient = useQueryClient()

  const handleEvent = useCallback(
    (data: SSEEventData) => {
      const repoId = data.repo_id as string | undefined
      const orgId = data.org_id as string | undefined

      switch (data.event) {
        case "analysis.queued":
        case "analysis.started":
        case "analysis.completed":
        case "analysis.failed":
        case "analysis.skipped":
          if (repoId) {
            queryClient.invalidateQueries({ queryKey: ["analyses", repoId] })
            queryClient.invalidateQueries({
              queryKey: ["issues", "repo", repoId],
            })
            queryClient.invalidateQueries({ queryKey: ["repositories"] })
            queryClient.invalidateQueries({
              queryKey: ["repository", repoId],
            })
          }
          break

        case "fix.generating":
        case "fix.ready":
        case "fix.delivering":
        case "fix.delivered":
        case "fix.failed":
        case "fix.rejected":
          if (repoId) {
            queryClient.invalidateQueries({
              queryKey: ["fixes", "repo", repoId],
            })
          }
          break

        case "pr.opened":
        case "pr.updated":
        case "pr.closed":
        case "pr.merged":
          if (repoId) {
            queryClient.invalidateQueries({
              queryKey: ["fixes", "repo", repoId],
            })
          }
          break

        case "installation.syncing":
        case "installation.synced":
        case "installation.created":
        case "installation.deleted":
          queryClient.invalidateQueries({ queryKey: ["installations"] })
          queryClient.invalidateQueries({ queryKey: ["repositories"] })
          if (orgId) {
            queryClient.invalidateQueries({
              queryKey: ["organizations", orgId],
            })
          }
          break

        case "repository.added":
        case "repository.disabled":
        case "repository.toggled":
          queryClient.invalidateQueries({ queryKey: ["repositories"] })
          if (repoId) {
            queryClient.invalidateQueries({
              queryKey: ["repository", repoId],
            })
          }
          break

        case "repository.action_pr_opened":
          if (repoId) {
            queryClient.invalidateQueries({
              queryKey: ["repository", repoId],
            })
          }
          break
      }
    },
    [queryClient],
  )

  useSSE(handleEvent)
}
