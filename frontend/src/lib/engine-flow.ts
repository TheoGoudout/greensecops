import {
  CircleCheck,
  CircleDashed,
  CircleSlash,
  GitPullRequest,
  Loader2,
  type LucideIcon,
  Play,
  RefreshCw,
  Wand2,
} from "lucide-react"
import type { FixStatus, PullRequestPublic } from "@/client"
import {
  actionBlockedReason,
  type EngineActionInput,
  isFixInFlight,
  type TargetActivity,
  targetActivity,
} from "@/lib/engine-actions"

/**
 * The four stages of an engine's flow, each reporting its own state.
 *
 * A **readout**, not a wizard. `engine-actions.ts` already decides which
 * buttons are live, and it does it well — but the only account of *why* was a
 * tooltip on a greyed button, so the page never said what was happening until
 * you hovered the thing it had stopped you doing. This states it once, above
 * the bar.
 *
 * Deliberately not a pointer marching left to right. The flow is not linear:
 * you re-scan after fixing, you reopen a pull request that was closed, you
 * regenerate a fix that landed badly. A stepper with a "current step" would
 * have to call each of those going backwards. So every stage reports its own
 * standing state side by side, and the only thing that moves is which one is
 * running.
 *
 * The running stage comes straight from `targetActivity` — the same call the
 * buttons make — so the rail cannot contradict the bar beneath it. At most one
 * stage is ever `running`, because an activity is one value.
 */

export type FlowStageId = "sync" | "scan" | "fix" | "deliver"

/**
 * `done` means this stage has produced something that still stands, not that
 * it happened once: files exist, a scan completed, a fix is written, a pull
 * request is open. `blocked` is the standing conditions' answer — no GitHub
 * access, a disabled target, a spent allowance — or a stage with nothing to
 * act on. `todo` is everything else, which is to say "you could do this now".
 */
export type FlowStageState = "blocked" | "todo" | "running" | "done"

export interface FlowStage {
  id: FlowStageId
  label: string
  state: FlowStageState
  icon: LucideIcon
  /** What this stage has to show for itself: "12 files", "Grade B", "PR #48". */
  detail: string
  /** Why it is blocked, or what it is doing. `null` on `todo` and `done`. */
  reason: string | null
  /**
   * The subset of `reason` that is a *standing* condition — no GitHub access,
   * a disabled target, a spent allowance, nothing here to act on — rather than
   * "something else is running right now". `null` when the only thing in the
   * way is the activity.
   *
   * The split is what stops the rail repeating itself. While one stage runs,
   * the other three are all blocked by that same one activity, and captioning
   * each with a truncated copy of the sentence already printed under the rail
   * says nothing three more times. A standing condition is the opposite: it is
   * specific to its stage and stated nowhere else, so it is what the caption
   * shows.
   */
  standing: string | null
}

/** Which stage each activity lights up. The map is total over the non-idle
 * activities, which is what makes "at most one running stage" a fact rather
 * than a convention. */
const STAGE_OF_ACTIVITY: Record<
  Exclude<TargetActivity, "idle">,
  FlowStageId
> = {
  scanning: "scan",
  generating: "fix",
  delivering: "deliver",
}

const LABELS: Record<FlowStageId, string> = {
  sync: "Sync",
  scan: "Analyse",
  fix: "Generate fixes",
  deliver: "Pull request",
}

const ICONS: Record<FlowStageId, LucideIcon> = {
  sync: RefreshCw,
  scan: Play,
  fix: Wand2,
  deliver: GitPullRequest,
}

/** What each stage's chip shows instead of its own icon, once it has an
 * outcome. Running is the spinner; the rest say whether there is anything
 * there. */
export const STATE_ICONS: Record<FlowStageState, LucideIcon> = {
  running: Loader2,
  done: CircleCheck,
  todo: CircleDashed,
  blocked: CircleSlash,
}

/**
 * Which stages an engine has at all.
 *
 * The same idea as `EngineActionBar`'s: Cloud has no files to rewrite, so it
 * declares neither `fix` nor `deliver` rather than showing two stages that can
 * never leave `blocked`. Only the CI engine declares `sync` — the other
 * engines' targets are registered by the user or by installation sync, not
 * re-fetched on demand.
 */
export type FlowCapabilities = Partial<Record<FlowStageId, boolean>>

const ALL_STAGES: readonly FlowStageId[] = ["sync", "scan", "fix", "deliver"]

export interface EngineFlowInput extends EngineActionInput {
  capabilities?: FlowCapabilities
  /** How many files this scope is analysing. `undefined` where unknown. */
  fileCount?: number
  /** When those files were last read from GitHub. CI engine only. */
  syncedAt?: string | null
  /** The latest completed scan's letter grade, if there is one. */
  grade?: string | null
  /** Whether any scan has ever finished here — a grade can be absent from a
   * clean scan, so this is asked separately. */
  hasCompletedScan?: boolean
  /** The pull request on this scope's deterministic branch, if one exists. */
  existingPr?: PullRequestPublic
  /** A sync request in flight. The CI sync is synchronous and leaves no row to
   * see, so unlike the other three it can only be known from here. */
  syncPending?: boolean
}

/**
 * Fix statuses that are something to show for the stage: a rewrite exists and
 * has not been thrown away.
 *
 * Deliberately wider than the deliver button's `ready` — a fix that has already
 * shipped is still a fix this target has — and narrower than "not failed": a
 * rejected or superseded one has been withdrawn, and a `no_op` rewrite changed
 * nothing, so counting those would report work that is not there.
 */
const WRITTEN_FIX: ReadonlySet<FixStatus> = new Set<FixStatus>([
  "ready",
  "delivered",
  "landed",
])

function writtenFixCount(input: EngineFlowInput): number {
  return (input.fixStatuses ?? []).filter((s) => WRITTEN_FIX.has(s)).length
}

/** Only the three nouns this file counts, so "fix" does not become "fixs". */
const PLURALS: Record<string, string> = {
  file: "files",
  finding: "findings",
  fix: "fixes",
}

/**
 * The reason `action` is blocked when nothing is running — the standing
 * conditions alone.
 *
 * Asks `actionBlockedReason` the same question with every source of activity
 * removed, rather than re-listing the conditions here: they are checked
 * widest-first and ahead of the activity table, so what survives with an idle
 * input is exactly the standing half.
 */
function standingReason(
  action: Parameters<typeof actionBlockedReason>[0],
  input: EngineFlowInput,
): string | null {
  return actionBlockedReason(action, {
    ...input,
    activity: "idle",
    scanStatus: undefined,
    fixStatuses: [],
    pending: {},
  })
}

function pluralize(count: number, noun: string): string {
  return `${count} ${count === 1 ? noun : PLURALS[noun]}`
}

/** How long ago, in the coarsest unit that is still true. */
function ago(iso: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (seconds < 90) return "just now"
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 48) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

function syncStage(input: EngineFlowInput, running: boolean): FlowStage {
  const blocked = actionBlockedReason("sync", input)
  const count = input.fileCount
  const parts: string[] = []
  if (count !== undefined) parts.push(pluralize(count, "file"))
  if (input.syncedAt) parts.push(ago(input.syncedAt))
  return {
    id: "sync",
    label: LABELS.sync,
    icon: ICONS.sync,
    state: running ? "running" : blocked ? "blocked" : count ? "done" : "todo",
    detail: running
      ? "Reading from GitHub…"
      : parts.length
        ? parts.join(" · ")
        : "Nothing read yet",
    reason: running ? "Reading files from GitHub" : blocked,
    standing: running ? null : standingReason("sync", input),
  }
}

function scanStage(input: EngineFlowInput, running: boolean): FlowStage {
  const blocked = actionBlockedReason("scan", input)
  const open = input.openFindingCount ?? 0
  const detail = input.hasCompletedScan
    ? [input.grade ? `Grade ${input.grade}` : null, pluralize(open, "finding")]
        .filter(Boolean)
        .join(" · ")
    : "Never analysed"
  return {
    id: "scan",
    label: LABELS.scan,
    icon: ICONS.scan,
    state: running
      ? "running"
      : blocked
        ? "blocked"
        : input.hasCompletedScan
          ? "done"
          : "todo",
    detail: running ? "Analysing…" : detail,
    reason: running ? "An analysis is running" : blocked,
    standing: running ? null : standingReason("scan", input),
  }
}

function fixStage(input: EngineFlowInput, running: boolean): FlowStage {
  // Two different "cannot": the standing conditions, and simply having nothing
  // to write a fix for. Both grey the stage; only the first is a problem.
  const blocked =
    actionBlockedReason("generate", input) ??
    ((input.openFindingCount ?? 0) > 0 ? null : "No open findings to fix")
  const ready = writtenFixCount(input)
  return {
    id: "fix",
    label: LABELS.fix,
    icon: ICONS.fix,
    state: running ? "running" : ready ? "done" : blocked ? "blocked" : "todo",
    detail: running
      ? "Writing fixes…"
      : ready
        ? `${pluralize(ready, "fix")} ready`
        : "No fix written",
    // A stage that is `done` says nothing, even when a standing condition would
    // block writing *more*: the fixes it reports are real and the bar below
    // already explains why the button is off.
    reason: running ? "Fixes are being generated" : ready ? null : blocked,
    // "No open findings to fix" is a standing fact about this stage, not an
    // activity, so it belongs in the caption, where it is the only account of
    // why. A stage with fixes to show says nothing: they are the better answer.
    standing:
      running || ready
        ? null
        : (standingReason("generate", input) ??
          ((input.openFindingCount ?? 0) > 0
            ? null
            : "No open findings to fix")),
  }
}

function deliverStage(input: EngineFlowInput, running: boolean): FlowStage {
  const pr = input.existingPr
  const blocked =
    actionBlockedReason("deliver", input) ??
    (pr || (input.fixStatuses ?? []).includes("ready")
      ? null
      : "No fix is ready to deliver")
  const state: FlowStageState = running
    ? "running"
    : pr && pr.pr_state !== "closed"
      ? "done"
      : blocked
        ? "blocked"
        : "todo"
  // The state, not the number: `PullRequestPublic` carries no number, and
  // scraping one out of `pr_url` would be a second place that knows GitHub's
  // URL shape. What the reader needs here is whether it is still open.
  const detail = pr
    ? `PR ${pr.pr_state ?? "opened"}`
    : blocked
      ? "Not opened"
      : "Ready to open"
  return {
    id: "deliver",
    label: LABELS.deliver,
    icon: ICONS.deliver,
    state,
    detail: running ? "Opening…" : detail,
    reason: running ? "A pull request is being opened" : blocked,
    standing:
      state === "blocked"
        ? (standingReason("deliver", input) ??
          ((input.fixStatuses ?? []).includes("ready")
            ? null
            : "No fix is ready to deliver"))
        : null,
  }
}

/**
 * The stages this engine declares, each in its current state.
 *
 * Order is fixed and matches the order the work happens in when it happens in
 * order — which reads as a flow without claiming the user is at any particular
 * point in one.
 */
export function engineFlow(input: EngineFlowInput): FlowStage[] {
  const activity = targetActivity(input)
  const runningStage = activity === "idle" ? null : STAGE_OF_ACTIVITY[activity]
  const builders: Record<
    FlowStageId,
    (input: EngineFlowInput, running: boolean) => FlowStage
  > = { sync: syncStage, scan: scanStage, fix: fixStage, deliver: deliverStage }

  return ALL_STAGES.filter((id) => input.capabilities?.[id] !== false).map(
    (id) =>
      builders[id](
        input,
        // The sync stage is the exception: it is a synchronous request with no
        // row behind it, so nothing but the mutation itself can report it.
        id === "sync" ? !!input.syncPending : runningStage === id,
      ),
  )
}

/** Whether any fix in this scope is mid-flight, for callers assembling
 * `readyFixCount` from a fix list. Re-exported so a page needs one import. */
export { isFixInFlight }
