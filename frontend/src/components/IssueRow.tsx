import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Bell, BellOff, Loader2 } from "lucide-react"
import { toast } from "sonner"
import { type IssuePublic, IssuesService } from "@/client"
import { CategoryIcon } from "@/components/CategoryIcon"
import { SeverityChip } from "@/components/SeverityChip"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { issueStatusColor, issueStatusLabel } from "@/lib/status-colors"
import { apiErrorDetail } from "@/utils"

interface IssueRowProps {
  issue: IssuePublic
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
        ? IssuesService.unignoreIssue({ issueId: issue.id })
        : IssuesService.ignoreIssue({ issueId: issue.id }),
    onSuccess: () => {
      toast.success(ignored ? "Issue unignored" : "Issue ignored")
      queryClient.invalidateQueries({ queryKey: ["issues", "repo", repoId] })
      queryClient.invalidateQueries({ queryKey: ["issues", "open"] })
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
          <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-mono bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300">
            {issue.rule_slug}
          </span>
          {issue.status && issue.status !== "open" && (
            <span
              className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium capitalize ${issueStatusColor(issue.status)}`}
            >
              {issueStatusLabel(issue.status)}
            </span>
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
