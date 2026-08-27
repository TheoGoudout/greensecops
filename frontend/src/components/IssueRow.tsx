import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Bell, BellOff, Loader2 } from "lucide-react"
import { toast } from "sonner"
import { type WorkflowFindingPublic, WorkflowService } from "@/client"
import { CategoryIcon } from "@/components/CategoryIcon"
import { RuleSlugChip } from "@/components/RuleSlugChip"
import { SeverityChip } from "@/components/SeverityChip"
import { StatusPill } from "@/components/StatusPill"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { apiErrorDetail } from "@/lib/api-error"
import { findingStatusColor, findingStatusLabel } from "@/lib/status-colors"

interface IssueRowProps {
  issue: WorkflowFindingPublic
  repoId: string
  checked?: boolean
  onCheckedChange?: () => void
  isAccessible?: boolean
}

export function IssueRow({
  issue,
  repoId,
  checked,
  onCheckedChange,
  isAccessible = true,
}: IssueRowProps) {
  const queryClient = useQueryClient()
  const ignored = issue.status === "ignored"
  // While muted, a violation isn't a fix candidate — hide its selection box.
  const hasCheckbox = onCheckedChange !== undefined && !ignored

  const muteMutation = useMutation({
    mutationFn: () =>
      ignored
        ? WorkflowService.unignoreFinding({ findingId: issue.id })
        : WorkflowService.ignoreFinding({ findingId: issue.id }),
    onSuccess: () => {
      toast.success(ignored ? "Issue unignored" : "Issue ignored")
      queryClient.invalidateQueries({ queryKey: ["findings", "repo", repoId] })
      queryClient.invalidateQueries({ queryKey: ["findings", "open"] })
    },
    onError: (error) =>
      toast.error(
        ignored ? "Failed to unignore issue" : "Failed to ignore issue",
        {
          description: apiErrorDetail(error),
        },
      ),
  })

  return (
    <div
      className={`flex items-start gap-3 px-6 py-4 ${ignored ? "opacity-60" : ""}`}
    >
      {hasCheckbox && (
        <Checkbox
          checked={checked}
          onCheckedChange={onCheckedChange}
          className="mt-0.5 shrink-0"
        />
      )}
      <CategoryIcon
        category={issue.category}
        className="mt-0.5 shrink-0 text-base"
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <SeverityChip severity={issue.severity} />
          <RuleSlugChip>{issue.rule_slug}</RuleSlugChip>
          {issue.status && issue.status !== "open" && (
            <StatusPill
              colorClass={findingStatusColor(issue.status)}
              className="inline-flex items-center capitalize"
            >
              {findingStatusLabel(issue.status)}
            </StatusPill>
          )}
          {issue.needs_manual_work && (
            <StatusPill
              colorClass="bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300"
              className="inline-flex items-center"
              title={
                issue.manual_work_note ??
                "The AI fix couldn't resolve this automatically"
              }
            >
              Needs manual work
            </StatusPill>
          )}
          <span className="text-sm break-words min-w-0">{issue.message}</span>
        </div>
        {issue.line_start != null && (
          <p className="text-xs text-muted-foreground mt-0.5">
            line {issue.line_start}
            {issue.line_end && issue.line_end !== issue.line_start
              ? `–${issue.line_end}`
              : ""}
          </p>
        )}
      </div>
      <Button
        variant="ghost"
        size="sm"
        className="h-7 shrink-0 gap-1.5 text-xs text-muted-foreground"
        onClick={() => muteMutation.mutate()}
        disabled={!isAccessible || muteMutation.isPending}
        title={ignored ? "Unignore this issue" : "Ignore this issue"}
      >
        {muteMutation.isPending ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : ignored ? (
          <Bell className="h-3.5 w-3.5" />
        ) : (
          <BellOff className="h-3.5 w-3.5" />
        )}
        {ignored ? "Unignore" : "Ignore"}
      </Button>
    </div>
  )
}
