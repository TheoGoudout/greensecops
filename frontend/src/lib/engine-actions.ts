import { GitPullRequest, type LucideIcon, Play, Wand2 } from "lucide-react"
import type { FixStatus, PullRequestPublic, ScanStatus } from "@/client"
import { labelForPr } from "@/lib/delivery"
import { isScanInFlight } from "@/lib/scan-polling"

/**
 * Which actions an engine target offers right now, and why not.
 *
 * Every engine asks the same three things of a target — scan it, write fixes
 * for it, open a pull request with them — and every engine page used to answer
 * "may I?" with its own pile of `disabled={...}` expressions. They disagreed:
 * only the CI pages checked `isAccessible`, only Terraform and Ansible checked
 * the target's `enabled` flag on every action, and *none* of them looked at the
 * scan status. `isScanInFlight` existed and drove the spinner badge, but no
 * button ever consulted it, so "Generate fixes" stayed live throughout a
 * running analysis and the request was accepted, queued, and then quietly
 * dropped by the worker's Redis lock.
 *
 * This module is the one answer. It mirrors
 * `backend/app/services/state_machines/engine_target.py` — same activities,
 * same precedence, same blocking table, and deliberately the same reason
 * strings, so a 409 that races past a disabled button reads exactly like the
 * tooltip that should have stopped it.
 */

/** Fix statuses a worker is actively processing. */
export const FIX_IN_FLIGHT: ReadonlySet<FixStatus> = new Set<FixStatus>([
  "pending",
  "generating",
  "delivering",
])

export function isFixInFlight(status: FixStatus | null | undefined): boolean {
  return status != null && FIX_IN_FLIGHT.has(status)
}

export type EngineActionId = "scan" | "generate" | "deliver"

/**
 * What a target is busy with. Derived from data the pages already fetch — the
 * target's latest scan status and its fixes' statuses — not from a field.
 */
export type TargetActivity = "idle" | "scanning" | "generating" | "delivering"

/** Reported when several hold at once: a scan outranks fix work because it
 * rewrites what the fixes are about; a delivery outranks generation because it
 * names the shorter, more specific wait. */
const PRECEDENCE: readonly TargetActivity[] = [
  "scanning",
  "delivering",
  "generating",
]

/** Which activities refuse which action. `generate` is the one action a
 * `generating` target still allows: writing a fix for file B while file A's is
 * in flight is ordinary work, and the server skips a file whose own fix a
 * worker holds. */
const BLOCKS: Record<EngineActionId, ReadonlySet<TargetActivity>> = {
  scan: new Set<TargetActivity>(["scanning", "generating", "delivering"]),
  generate: new Set<TargetActivity>(["scanning", "delivering"]),
  deliver: new Set<TargetActivity>(["scanning", "generating", "delivering"]),
}

/** Kept word-for-word in step with the backend's `REASONS`. */
const REASONS: Record<Exclude<TargetActivity, "idle">, string> = {
  scanning: "a scan is already running",
  generating: "fixes are being generated",
  delivering: "a pull request is being opened",
}

/** The verb each action names itself by, matching the backend's `TargetAction`
 * values so the two halves of a sentence never drift apart. */
const VERBS: Record<EngineActionId, string> = {
  scan: "start a scan",
  generate: "generate fixes",
  deliver: "open a pull request",
}

/** Whether the button acts on one file, one registered target, or a whole
 * repository. Only the wording of the generate button differs. */
export type ActionScope = "repo" | "target" | "file"

export interface EngineActionInput {
  /** What this target is called in a sentence: "Terraform root", "workflow file". */
  targetLabel: string
  scope: ActionScope
  /** The repo's GitHub App access. Absent means "not applicable" (Cloud). */
  isAccessible?: boolean
  /** A registered target's enable flag. Workflow files have none. */
  enabled?: boolean
  /** This scope's latest scan status, or every unfinished one for a repository. */
  scanStatus?: ScanStatus | readonly (ScanStatus | null | undefined)[] | null
  /** Every fix in this scope. */
  fixStatuses?: readonly FixStatus[]
  /** Findings a fix could still be written for. */
  openFindingCount?: number
  /**
   * What to say when `openFindingCount` is zero. Defaults to "No open findings
   * to fix", which is right everywhere the button acts on the whole target —
   * but the CI page's repository-wide bar acts on a *selection*, and there an
   * empty count means the user deselected everything, not that the repository
   * is clean.
   */
  noFindingsReason?: string
  /** The pull request on this scope's deterministic branch, if one exists. */
  existingPr?: PullRequestPublic
  /**
   * A fix that is not `ready` but can still be re-delivered — the workflow
   * engine reopens a delivered fix whose PR was closed. See `deliverAction`.
   */
  reopenable?: boolean
  /** Appended to the generate button's label, e.g. "Generate fixes (3)". */
  count?: number
  /** Trigger requests currently in flight, by action. */
  pending?: Partial<Record<EngineActionId, boolean>>
}

export interface EngineAction {
  label: string
  icon: LucideIcon
  /** Show a spinner: either the request or the work it started is in flight. */
  busy: boolean
  disabled: boolean
  /** Sentence for the tooltip when disabled, else null. */
  reason: string | null
  /** Delivery only: whether to force past the closed-PR guard. */
  force: boolean
}

function asArray<T>(value: T | readonly T[] | null | undefined): readonly T[] {
  if (value == null) return []
  return Array.isArray(value) ? value : [value as T]
}

/** What this scope is busy with. Mirrors the backend's `activity_of`. */
export function targetActivity(input: EngineActionInput): TargetActivity {
  const found = new Set<TargetActivity>()
  if (asArray(input.scanStatus).some(isScanInFlight)) found.add("scanning")
  for (const status of input.fixStatuses ?? []) {
    if (status === "delivering") found.add("delivering")
    else if (status === "pending" || status === "generating") {
      found.add("generating")
    }
  }
  return PRECEDENCE.find((activity) => found.has(activity)) ?? "idle"
}

/**
 * Why `action` cannot run *right now*, or null — access, the enable flag, and
 * whatever the target is busy with. Ordered widest-first: an inaccessible repo
 * or a disabled target is a standing condition worth saying before "something
 * else is running", which is only temporary.
 *
 * Deliberately says nothing about whether there is any work to do; that is the
 * caller's question and differs per button. Exported as
 * :func:`actionBlockedReason` for the engine-specific actions that sit in an
 * overflow menu — regenerating every fix obeys the same activity rules as
 * generating one, but not the same "is anything selected?" rule.
 */
function blockedReason(
  action: EngineActionId,
  activity: TargetActivity,
  input: EngineActionInput,
): string | null {
  if (input.isAccessible === false) {
    return "GitHub access to this repository was lost"
  }
  if (input.enabled === false) {
    return `Enable this ${input.targetLabel.toLowerCase()} first`
  }
  if (activity !== "idle" && BLOCKS[action].has(activity)) {
    return `Cannot ${VERBS[action]} while ${REASONS[activity]}`
  }
  return null
}

/** :func:`blockedReason` for a caller that has an input but no activity yet. */
export function actionBlockedReason(
  action: EngineActionId,
  input: EngineActionInput,
): string | null {
  return blockedReason(action, targetActivity(input), input)
}

/**
 * The three actions, ready to render.
 *
 * Always all three, even when there is nothing to act on — a button that
 * disappears teaches nobody why, and "the user should find similar buttons on
 * each engine" is the whole point. An engine that genuinely lacks an action
 * (Cloud has no fixes) omits it at the render site instead, through
 * `EngineActionBar`'s capabilities.
 */
export function engineActions(
  input: EngineActionInput,
): Record<EngineActionId, EngineAction> {
  const activity = targetActivity(input)
  const pending = input.pending ?? {}
  const fixStatuses = input.fixStatuses ?? []
  const canDeliver = fixStatuses.includes("ready") || input.reopenable === true
  const hasFindings = (input.openFindingCount ?? 0) > 0

  const scanBlocked = blockedReason("scan", activity, input)
  const generateBlocked = blockedReason("generate", activity, input)
  const deliverBlocked = blockedReason("deliver", activity, input)

  // Always "Generate", never "Regenerate". The batch endpoints write a fix for
  // whatever has none and leave the rest alone, so "Regenerate" would promise
  // something they do not do. Discarding and re-queueing an existing fix is a
  // separate endpoint on the one engine that has one, and belongs in that
  // engine's overflow menu rather than hiding under a shared label.
  const noun = input.scope === "file" ? "fix" : "fixes"
  const countSuffix = input.count === undefined ? "" : ` (${input.count})`
  const delivery = labelForPr(input.existingPr, "PR")

  return {
    scan: {
      label: pending.scan
        ? "Queuing…"
        : activity === "scanning"
          ? "Scanning…"
          : "Scan now",
      icon: Play,
      busy: !!pending.scan || activity === "scanning",
      disabled: !!scanBlocked || !!pending.scan,
      reason: scanBlocked,
      force: false,
    },
    generate: {
      label:
        pending.generate || activity === "generating"
          ? "Generating…"
          : `Generate ${noun}${countSuffix}`,
      icon: Wand2,
      busy: !!pending.generate || activity === "generating",
      disabled: !!generateBlocked || !!pending.generate || !hasFindings,
      reason:
        generateBlocked ??
        (hasFindings
          ? null
          : (input.noFindingsReason ?? "No open findings to fix")),
      force: false,
    },
    deliver: {
      label: pending.deliver ? "Queuing…" : delivery.label,
      icon: GitPullRequest,
      busy: !!pending.deliver || activity === "delivering",
      disabled: !!deliverBlocked || !!pending.deliver || !canDeliver,
      reason:
        deliverBlocked ?? (canDeliver ? null : "No fix is ready to deliver"),
      force: delivery.force,
    },
  }
}
