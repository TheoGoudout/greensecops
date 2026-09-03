import { useQuery } from "@tanstack/react-query"
import { RepositoriesService } from "@/client"
import { pollForActivity } from "@/lib/scan-polling"

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
    // This row carries the repository's `activity`, and every engine page gates
    // its buttons on it — so it is the one read that must not sit still. SSE
    // invalidates it faster on the CI engine, but only while the stream is up,
    // and the other engines have no stream at all. See `pollForActivity`: five
    // seconds while something is running, thirty when nothing appears to be,
    // because "nothing appears to be" is the answer this can be wrong about.
    refetchInterval: (query) => pollForActivity([query.state.data?.activity]),
  })
  const isAccessible = repo?.is_accessible ?? true
  return { repo, isLoading, isAccessible }
}
