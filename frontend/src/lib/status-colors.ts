import type { FixStatus, IssueStatus } from "@/client"

export function analysisStatusColor(status: string): string {
  switch (status) {
    case "completed":
      return "bg-green-500/15 text-green-700 dark:text-green-400"
    case "running":
      return "bg-blue-500/15 text-blue-700 dark:text-blue-400"
    case "failed":
      return "bg-red-500/15 text-red-700 dark:text-red-400"
    case "pending":
      return "bg-yellow-500/15 text-yellow-700 dark:text-yellow-400"
    case "no_workflows":
      return "bg-muted text-muted-foreground"
    default:
      return "bg-muted text-muted-foreground"
  }
}

export function analysisStatusLabel(status: string): string {
  switch (status) {
    case "no_workflows":
      return "No workflows"
    default:
      return status.replace(/_/g, " ")
  }
}

export function fixStatusColor(status: FixStatus): string {
  switch (status) {
    case "landed":
      return "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400"
    case "delivered":
      return "bg-green-500/15 text-green-700 dark:text-green-400"
    case "ready":
      return "bg-blue-500/15 text-blue-700 dark:text-blue-400"
    case "failed":
      return "bg-red-500/15 text-red-700 dark:text-red-400"
    case "rejected_by_user":
    case "superseded_by_closed_pr":
    case "superseded_by_deleted_file":
      return "bg-muted text-muted-foreground line-through"
    default:
      return "bg-yellow-500/15 text-yellow-700 dark:text-yellow-400"
  }
}

export function issueStatusColor(status: IssueStatus): string {
  switch (status) {
    case "resolved":
      return "bg-green-500/15 text-green-700 dark:text-green-400"
    case "fix_in_progress":
      return "bg-blue-500/15 text-blue-700 dark:text-blue-400"
    case "ignored":
      return "bg-muted text-muted-foreground"
    default:
      return "bg-yellow-500/15 text-yellow-700 dark:text-yellow-400"
  }
}

export function issueStatusLabel(status: IssueStatus): string {
  switch (status) {
    case "fix_in_progress":
      return "Fix in progress"
    default:
      return status.replace(/_/g, " ")
  }
}
