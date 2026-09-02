import { useQuery } from "@tanstack/react-query"
import { RepositoriesService } from "@/client"

/**
 * Fetch a repository by id. The `["repository", repoId]` query key is shared
 * with the SSE invalidations in useRepoEvents — keep them in sync.
 *
 * `repoId` is optional because one caller reaches it through a search
 * parameter that may be absent (the fix detail page, opened without a repo
 * context). Without an id there is nothing to ask for, so the query stays
 * disabled and `isAccessible` falls back to `true` — the same "not known here"
 * default it already uses before the answer lands.
 */
export function useRepository(repoId: string | undefined) {
  const { data: repo, isLoading } = useQuery({
    queryKey: ["repository", repoId],
    queryFn: () => RepositoriesService.getRepository({ repoId: repoId! }),
    enabled: !!repoId,
  })
  const isAccessible = repo?.is_accessible ?? true
  return { repo, isLoading, isAccessible }
}
