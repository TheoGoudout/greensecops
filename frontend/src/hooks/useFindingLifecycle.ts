import { useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { apiErrorDetail } from "@/lib/api-error"

/**
 * Ignore/unignore for one finding, shared by every engine's finding row.
 *
 * Every engine answers the same `PATCH /{engine}/findings/{id}` with an
 * `{ ignored }` body, so only which service method to call and which query
 * keys to refresh differ per engine.
 */
export function useFindingLifecycle({
  findingId,
  ignored,
  update,
  invalidateKeys,
}: {
  findingId: string
  ignored: boolean
  /** The engine's `updateFinding`, given the id and the new `ignored` value. */
  update: (findingId: string, ignored: boolean) => Promise<unknown>
  invalidateKeys: readonly (readonly unknown[])[]
}) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => update(findingId, !ignored),
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
