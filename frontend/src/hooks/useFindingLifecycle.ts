import { useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { apiErrorDetail } from "@/lib/api-error"

/**
 * Ignore/unignore for one finding, shared across Terraform, Docker, Cloud and
 * Ansible — the same action IssueRow has always had for Workflow findings,
 * generalized once the four other engines' routes caught up to it.
 *
 * A named hook (not inlined in each `*FindingRow`) so the mutation, toast and
 * invalidation wiring exists once; only which service method to call and
 * which query keys to refresh differ per engine.
 */
export function useFindingLifecycle({
  findingId,
  ignored,
  ignore,
  unignore,
  invalidateKeys,
}: {
  findingId: string
  ignored: boolean
  ignore: (findingId: string) => Promise<unknown>
  unignore: (findingId: string) => Promise<unknown>
  invalidateKeys: readonly (readonly unknown[])[]
}) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => (ignored ? unignore(findingId) : ignore(findingId)),
    onSuccess: () => {
      toast.success(ignored ? "Finding unignored" : "Finding ignored")
      for (const key of invalidateKeys) {
        queryClient.invalidateQueries({ queryKey: key as unknown[] })
      }
    },
    onError: (error) =>
      toast.error(
        ignored ? "Failed to unignore finding" : "Failed to ignore finding",
        { description: apiErrorDetail(error) },
      ),
  })
}
