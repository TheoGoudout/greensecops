import { type WorkflowFindingPublic, WorkflowService } from "@/client"
import { CategoryIcon } from "@/components/CategoryIcon"
import { FindingIgnoreButton } from "@/components/FindingRow"
import { RuleSlugChip } from "@/components/RuleSlugChip"
import { SeverityChip } from "@/components/SeverityChip"
import { StatusPill } from "@/components/StatusPill"
import { Checkbox } from "@/components/ui/checkbox"
import { useFindingLifecycle } from "@/hooks/useFindingLifecycle"
import { type EngineActionInput, ignoreAction } from "@/lib/engine-actions"
import { findingStatusColor, findingStatusLabel } from "@/lib/status-colors"

interface IssueRowProps {
  issue: WorkflowFindingPublic
  repoId: string
  checked?: boolean
  onCheckedChange?: () => void
  /**
   * What the repository is doing, from the page's own action input. A running
   * analysis is about to replace this issue, so muting it is refused — and a
   * resolved one cannot be muted at all.
   */
  targetState: EngineActionInput
}

export function IssueRow({
  issue,
  repoId,
  checked,
  onCheckedChange,
  targetState,
}: IssueRowProps) {
  const ignored = issue.status === "ignored"
  // While muted, a violation isn't a fix candidate — hide its selection box.
  const hasCheckbox = onCheckedChange !== undefined && !ignored

  const muteMutation = useFindingLifecycle({
    findingId: issue.id,
    ignored,
    update: (findingId, ignored) =>
      WorkflowService.updateFinding({ findingId, requestBody: { ignored } }),
    invalidateKeys: [
      ["findings", "repo", repoId],
      ["findings", "open"],
    ],
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
              colorClass="bg-warning/15 text-warning-ink"
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
      <FindingIgnoreButton
        action={ignoreAction(issue.status, {
          ...targetState,
          pending: { ignore: muteMutation.isPending },
        })}
        onClick={() => muteMutation.mutate()}
      />
    </div>
  )
}
