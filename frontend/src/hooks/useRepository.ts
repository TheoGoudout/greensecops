import { useQuery } from "@tanstack/react-query"
import { RepositoriesService } from "@/client"

/**
 * Fetch a repository by id. The `["repository", repoId]` query key is shared
 * with the SSE invalidations in useRepoEvents — keep them in sync.
 */
export function useRepository(repoId: string) {
  const { data: repo, isLoading } = useQuery({
    queryKey: ["repository", repoId],
    queryFn: () => RepositoriesService.getRepository({ repoId }),
  })
  const isAccessible = repo?.is_accessible ?? true
  return { repo, isLoading, isAccessible }
}
