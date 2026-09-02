import type {
  CIStatus,
  CloudAccountStatus,
  DynamicAnalysisStatus,
  FindingStatus,
  FixStatus,
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

type Tone = keyof typeof STATUS_CLASSES

/**
 * Build a status→class lookup from a partial map plus a fallback.
 *
 * Each of these used to be a `switch` returning `STATUS_CLASSES.x` per arm —
 * eight of them, ~15 lines each, all saying "this value looks like that tone".
 * A table says the same thing in one line per value, and the shape is uniform
 * enough that a reader can check a whole domain at a glance.
 */
function toneMap<T extends string>(
  tones: Partial<Record<T, Tone>>,
  fallback: Tone,
): (status: T) => string {
  return (status) => STATUS_CLASSES[tones[status] ?? fallback]
}

/**
 * Humanise a status value, with overrides for the ones that need more than
 * underscore-to-space.
 */
function labeller<T extends string>(
  overrides: Partial<Record<T, string>> = {},
): (status: T) => string {
  return (status) => overrides[status] ?? status.replace(/_/g, " ")
}

export const scanStatusColor = toneMap<ScanStatus>(
  {
    completed: "success",
    running: "running",
    failed: "failed",
    queued: "pending",
  },
  "muted",
)

export const scanStatusLabel = labeller<ScanStatus>({
  no_targets: "No targets",
})

export const fixStatusColor = toneMap<FixStatus>(
  {
    landed: "landed",
    delivered: "success",
    ready: "running",
    failed: "failed",
    rejected_by_user: "mutedStruck",
    superseded_by_closed_pr: "mutedStruck",
    superseded_by_deleted_file: "mutedStruck",
    // Withheld at delivery because the rewrite resolved nothing — a withdrawal
    // like the three above it, not the yellow "still working on it" the
    // fallback would give it.
    no_op: "mutedStruck",
  },
  "pending",
)

export const findingStatusColor = toneMap<FindingStatus>(
  {
    resolved: "success",
    fix_in_progress: "running",
    ignored: "muted",
  },
  "pending",
)

export const findingStatusLabel = labeller<FindingStatus>({
  fix_in_progress: "Fix in progress",
})

export const ciStatusColor = toneMap<CIStatus>(
  {
    success: "success",
    failure: "failed",
    pending: "pending",
  },
  "muted",
)

export const ciStatusLabel = labeller<CIStatus>({
  success: "CI passing",
  failure: "CI failing",
  pending: "CI running",
  none: "No CI",
})

export const reviewDecisionColor = toneMap<ReviewDecision>(
  {
    approved: "success",
    changes_requested: "failed",
  },
  "pending",
)

export const reviewDecisionLabel = labeller<ReviewDecision>({
  approved: "Approved",
  changes_requested: "Changes requested",
  review_required: "Review required",
})

export const dynamicStatusColor = toneMap<DynamicAnalysisStatus>(
  {
    enriched: "success",
    running: "running",
    failed: "failed",
  },
  "pending",
)

export const cloudAccountStatusColor = toneMap<CloudAccountStatus>(
  {
    connected: "success",
    error: "failed",
    disabled: "mutedStruck",
  },
  "pending",
)

export const cloudAccountStatusLabel = labeller<CloudAccountStatus>()

/**
 * GitHub's `mergeable_state` as a compact, human indicator.
 *
 * Only surfaced when it carries a signal worth acting on: "clean" and unknown
 * states return null rather than adding a pill that says nothing.
 */
const MERGEABLE: Record<string, { label: string; cls: Tone }> = {
  dirty: { label: "conflicts", cls: "failed" },
  behind: { label: "behind base", cls: "pending" },
  blocked: { label: "blocked", cls: "pending" },
  unstable: { label: "checks pending", cls: "pending" },
  clean: { label: "mergeable", cls: "success" },
}

export function mergeableIndicator(
  state: string | null | undefined,
): { label: string; cls: string } | null {
  const hit = state ? MERGEABLE[state] : undefined
  return hit ? { label: hit.label, cls: STATUS_CLASSES[hit.cls] } : null
}
