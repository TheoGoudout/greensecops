import type { IssuePublic } from "@/client"
import { CategoryIcon } from "@/components/CategoryIcon"
import { GenerateFixButton } from "@/components/GenerateFixButton"
import { SeverityChip } from "@/components/SeverityChip"
import { Checkbox } from "@/components/ui/checkbox"

interface IssueRowProps {
  issue: IssuePublic
  repoId: string
  checked?: boolean
  onCheckedChange?: () => void
}

export function IssueRow({
  issue,
  repoId,
  checked,
  onCheckedChange,
}: IssueRowProps) {
  const hasCheckbox = onCheckedChange !== undefined

  return (
    <div className="flex items-start gap-3 px-6 py-4">
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
          <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-mono bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300">
            {issue.rule_slug}
          </span>
          <span className="text-sm">{issue.message}</span>
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
      <GenerateFixButton
        issueId={issue.id}
        repoId={repoId}
        fixStatus={issue.fix_status}
      />
    </div>
  )
}
