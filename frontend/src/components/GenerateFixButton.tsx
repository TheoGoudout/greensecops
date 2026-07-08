import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Loader2, Wand2 } from "lucide-react"
import type { FixStatus } from "@/client"
import { FixesService } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"

interface GenerateFixButtonProps {
  issueId: string
  repoId: string
  fixStatus?: FixStatus | null
}

export function GenerateFixButton({
  issueId,
  repoId,
  fixStatus,
}: GenerateFixButtonProps) {
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: () =>
      FixesService.triggerFixGenerationForRepo({
        repoId,
        requestBody: { issue_ids: [issueId] },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["fixes"] })
      queryClient.invalidateQueries({ queryKey: ["issues"] })
    },
  })

  if (fixStatus === "delivered") {
    return (
      <Badge
        variant="outline"
        className="text-green-700 border-green-300 bg-green-50 dark:bg-green-950/30 dark:text-green-400 shrink-0"
      >
        Delivered
      </Badge>
    )
  }

  if (fixStatus === "ready") {
    return (
      <Badge
        variant="outline"
        className="text-green-700 border-green-300 bg-green-50 dark:bg-green-950/30 dark:text-green-400 shrink-0"
      >
        Ready
      </Badge>
    )
  }

  if (
    fixStatus === "pending" ||
    fixStatus === "generating" ||
    fixStatus === "delivering"
  ) {
    return (
      <Button variant="outline" size="sm" className="gap-1.5 shrink-0" disabled>
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        {fixStatus === "pending"
          ? "Queued"
          : fixStatus === "delivering"
            ? "Delivering…"
            : "Generating…"}
      </Button>
    )
  }

  return (
    <Button
      variant="outline"
      size="sm"
      className="gap-1.5 shrink-0"
      onClick={() => mutation.mutate()}
      disabled={mutation.isPending}
    >
      <Wand2 className="h-3.5 w-3.5" />
      {mutation.isPending ? "Queuing…" : "Generate fix"}
    </Button>
  )
}
