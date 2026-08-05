import type {
  CIStatus,
  CloudAccountStatus,
  DynamicAnalysisStatus,
  FixStatus,
  IssueStatus,
  ReviewDecision,
  ScanStatus,
} from "@/client"

// One palette of semantic status classes, mapped per domain below so the
// Tailwind tokens are defined exactly once.
const STATUS_CLASSES = {
  success: "bg-green-500/15 text-green-700 dark:text-green-400",
  landed: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
  running: "bg-blue-500/15 text-blue-700 dark:text-blue-400",
  failed: "bg-red-500/15 text-red-700 dark:text-red-400",
  pending: "bg-yellow-500/15 text-yellow-700 dark:text-yellow-400",
  muted: "bg-muted text-muted-foreground",
  mutedStruck: "bg-muted text-muted-foreground line-through",
} as const

export function analysisStatusColor(status: string): string {
  switch (status) {
    case "completed":
      return STATUS_CLASSES.success
    case "running":
      return STATUS_CLASSES.running
    case "failed":
      return STATUS_CLASSES.failed
    case "pending":
      return STATUS_CLASSES.pending
    default:
      return STATUS_CLASSES.muted
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
      return STATUS_CLASSES.landed
    case "delivered":
      return STATUS_CLASSES.success
    case "ready":
      return STATUS_CLASSES.running
    case "failed":
      return STATUS_CLASSES.failed
    case "rejected_by_user":
    case "superseded_by_closed_pr":
    case "superseded_by_deleted_file":
      return STATUS_CLASSES.mutedStruck
    default:
      return STATUS_CLASSES.pending
  }
}

export function issueStatusColor(status: IssueStatus): string {
  switch (status) {
    case "resolved":
      return STATUS_CLASSES.success
    case "fix_in_progress":
      return STATUS_CLASSES.running
    case "ignored":
      return STATUS_CLASSES.muted
    default:
      return STATUS_CLASSES.pending
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

export function ciStatusColor(status: CIStatus): string {
  switch (status) {
    case "success":
      return STATUS_CLASSES.success
    case "failure":
      return STATUS_CLASSES.failed
    case "pending":
      return STATUS_CLASSES.pending
    default:
      return STATUS_CLASSES.muted
  }
}

export function ciStatusLabel(status: CIStatus): string {
  switch (status) {
    case "success":
      return "CI passing"
    case "failure":
      return "CI failing"
    case "pending":
      return "CI running"
    default:
      return "No CI"
  }
}

export function reviewDecisionColor(decision: ReviewDecision): string {
  switch (decision) {
    case "approved":
      return STATUS_CLASSES.success
    case "changes_requested":
      return STATUS_CLASSES.failed
    default:
      return STATUS_CLASSES.pending
  }
}

export function reviewDecisionLabel(decision: ReviewDecision): string {
  switch (decision) {
    case "approved":
      return "Approved"
    case "changes_requested":
      return "Changes requested"
    default:
      return "Review required"
  }
}

export function scanStatusColor(status: ScanStatus): string {
  switch (status) {
    case "completed":
      return STATUS_CLASSES.success
    case "running":
      return STATUS_CLASSES.running
    case "failed":
      return STATUS_CLASSES.failed
    case "queued":
      return STATUS_CLASSES.pending
    default:
      return STATUS_CLASSES.muted
  }
}

export function scanStatusLabel(status: ScanStatus): string {
  switch (status) {
    case "no_targets":
      return "No targets"
    default:
      return status.replace(/_/g, " ")
  }
}

export function dynamicStatusColor(status: DynamicAnalysisStatus): string {
  switch (status) {
    case "enriched":
      return STATUS_CLASSES.success
    case "running":
      return STATUS_CLASSES.running
    case "failed":
      return STATUS_CLASSES.failed
    default:
      return STATUS_CLASSES.pending
  }
}

export function cloudAccountStatusColor(status: CloudAccountStatus): string {
  switch (status) {
    case "connected":
      return STATUS_CLASSES.success
    case "error":
      return STATUS_CLASSES.failed
    case "disabled":
      return STATUS_CLASSES.mutedStruck
    default:
      return STATUS_CLASSES.pending
  }
}

export function cloudAccountStatusLabel(status: CloudAccountStatus): string {
  return status.replace(/_/g, " ")
}

/**
 * GitHub's `mergeable_state` as a compact, human indicator.
 *
 * Only surfaced when it carries a signal worth acting on: "clean" and unknown
 * states return null rather than adding a pill that says nothing.
 */
export function mergeableIndicator(
  state: string | null | undefined,
): { label: string; cls: string } | null {
  switch (state) {
    case "dirty":
      return { label: "conflicts", cls: STATUS_CLASSES.failed }
    case "behind":
      return { label: "behind base", cls: STATUS_CLASSES.pending }
    case "blocked":
      return { label: "blocked", cls: STATUS_CLASSES.pending }
    case "unstable":
      return { label: "checks pending", cls: STATUS_CLASSES.pending }
    case "clean":
      return { label: "mergeable", cls: STATUS_CLASSES.success }
    default:
      return null
  }
}
