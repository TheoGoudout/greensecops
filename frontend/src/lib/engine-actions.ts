import {
  Bell,
  BellOff,
  GitPullRequest,
  type LucideIcon,
  Play,
  RefreshCw,
  Trash2,
  Wand2,
} from "lucide-react"
import type {
  TargetActivity as ClientTargetActivity,
  FindingStatus,
  FixStatus,
  PullRequestPublic,
  ScanStatus,
} from "@/client"
import { labelForPr } from "@/lib/delivery"
import { isScanInFlight } from "@/lib/scan-polling"

/**
 * Which actions an engine target offers right now, and why not.
 *
 * Every engine asks the same things of a target — scan it, write fixes for it,
 * open a pull request with them, remove it, mute one of its findings — and
 * every engine page used to answer "may I?" with its own pile of
 * `disabled={...}` expressions. They disagreed: only the CI pages checked
 * `isAccessible`, only Terraform and Ansible checked the target's `enabled`
 * flag on every action, and *none* of them looked at the scan status.
 * `isScanInFlight` existed and drove the spinner badge, but no button ever
 * consulted it, so "Generate fixes" stayed live throughout a running analysis
 * and the request was accepted, queued, and then quietly dropped by the
 * worker's Redis lock.
 *
 * This module is the one answer. It mirrors
 * `backend/app/services/state_machines/engine_target.py` — same activities,
 * same precedence, same blocking table, and deliberately the same reason
 * strings, so a 409 that races past a disabled button reads exactly like the
 * tooltip that should have stopped it. The quota reasons are the same sentence
 * the 402 carries, for the same reason; the backend hands them over ready-made
 * on `GET /billing/organizations/{org_id}/quotas` rather than letting this file
 * try to reproduce a plan's wording.
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

/**
 * Every action the blocking table rules on — the mirror of the backend's
 * `TargetAction`.
 *
 * The last three are not engine flows of their own, which is why only the first
 * three are drawn by `EngineActionBar`. They collide with the same in-flight
 * work, though, so they are ruled on here rather than by whichever page happens
 * to render them.
 */
export type TargetActionId =
  | "scan"
  | "generate"
  | "deliver"
  | "remove"
  | "ignore"
  | "sync"

/** The three the action bar draws. */
export type EngineActionId = Extract<
  TargetActionId,
  "scan" | "generate" | "deliver"
>

/**
 * What a target is busy with.
 *
 * Re-exported from the generated client rather than spelled out here: the
 * backend publishes this on every target and repository as
 * `ScanTargetPublicBase.activity`, so the browser now *reads* the value the 409
 * guard would decide from instead of only reconstructing it. The local
 * derivation stays — see `targetActivity` — because a page often holds fresher
 * fix statuses than the row it fetched, and because a request still in flight
 * has no server-side row to be seen in yet.
 */
export type TargetActivity = ClientTargetActivity

/** Reported when several hold at once: a scan outranks fix work because it
 * rewrites what the fixes are about; a delivery outranks generation because it
 * names the shorter, more specific wait. */
const PRECEDENCE: readonly TargetActivity[] = [
  "scanning",
  "delivering",
  "generating",
]

const BUSY: ReadonlySet<TargetActivity> = new Set<TargetActivity>([
  "scanning",
  "generating",
  "delivering",
])

/**
 * Which activities refuse which action.
 *
 * `generate` is the one *engine* action a `generating` target still allows:
 * writing a fix for file B while file A's is in flight is ordinary work, and
 * the server skips a file whose own fix a worker holds. `remove` joins the
 * one-at-a-time majority because deleting a target cascades its scans, findings
 * and fixes away underneath whoever is holding them.
 *
 * `ignore` and `sync` are refused by a scan alone: a scan is the only activity
 * that touches what they touch — it resolves findings out from under the ignore
 * transition, and rewrites the very files a sync would replace. Fix work reads
 * both and writes neither.
 */
const BLOCKS: Record<TargetActionId, ReadonlySet<TargetActivity>> = {
  scan: BUSY,
  generate: new Set<TargetActivity>(["scanning", "delivering"]),
  deliver: BUSY,
  remove: BUSY,
  ignore: new Set<TargetActivity>(["scanning"]),
  sync: new Set<TargetActivity>(["scanning"]),
}

/**
 * The activity an in-flight trigger request is about to create.
 *
 * Without this there is a window — between the click and the refetch that
 * follows the response — in which the server has no row to report yet and the
 * page still believes the target is idle. `pending.scan` greyed only the scan
 * button, so "Generate fixes" and "Create PR" stayed live over an analysis
 * already on its way: exactly the race the blocking table exists to stop, just
 * a second wide. Folding the pending request into the activity closes it with
 * no new state, and the tooltip it grows is the one the table already writes.
 *
 * `remove`, `ignore` and `sync` are absent because they create no activity —
 * they are refused *by* one. They still obey the pin, since they read the same
 * value.
 */
const PENDING_ACTIVITY: Partial<Record<TargetActionId, TargetActivity>> = {
  scan: "scanning",
  generate: "generating",
  deliver: "delivering",
}

/**
 * The one standing condition that is not about this target at all.
 *
 * Exported because a couple of GitHub-touching controls outside the three
 * actions — re-reading a repository's pull requests, say — have only this
 * condition to check, and a second copy of the sentence would be a second
 * thing to keep in step.
 */
export const NO_ACCESS_REASON = "GitHub access to this repository was lost"

/** Kept word-for-word in step with the backend's `REASONS`. */
const REASONS: Record<Exclude<TargetActivity, "idle">, string> = {
  scanning: "a scan is already running",
  generating: "fixes are being generated",
  delivering: "a pull request is being opened",
}

/** The verb each action names itself by, matching the backend's `TargetAction`
 * values so the two halves of a sentence never drift apart. */
const VERBS: Record<TargetActionId, string> = {
  scan: "start a scan",
  generate: "generate fixes",
  deliver: "open a pull request",
  remove: "remove this target",
  ignore: "change a finding",
  sync: "sync from GitHub",
}

/**
 * The allowance each action spends, or `null` for the ones that spend nothing.
 *
 * Only these two meters gate a button: `repos` is capacity checked when a
 * repository is enabled, not when it is acted on.
 */
const METERS: Record<TargetActionId, "analyses" | "fixes" | null> = {
  scan: "analyses",
  generate: "fixes",
  deliver: null,
  remove: null,
  ignore: null,
  sync: null,
}

/**
 * An organization's exhausted allowances, as the sentences the 402 would carry.
 *
 * Deliberately strings rather than numbers: reproducing "You've used all 50
 * analyses included in the Starter plan this month. Upgrade to Pro…" in the
 * browser would mean shipping the plan catalog too, and the two copies would
 * drift. `null` means the next unit goes through.
 */
export interface QuotaReasons {
  analyses?: string | null
  fixes?: string | null
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
  /** The owning org's spent allowances. Absent means "not known here". */
  quota?: QuotaReasons
  /**
   * What the server says this scope is busy with, straight off the target's or
   * repository's `activity` field.
   *
   * Unioned with the statuses below rather than replacing them: a list row is
   * authoritative about work started elsewhere — by the Action, a webhook, a
   * teammate — while an expanded card often holds fresher fix statuses than the
   * row it was drawn from. Neither is a superset of the other.
   */
  activity?: TargetActivity
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
  /**
   * Turn the generate button into a *re*-generate: it discards the fixes this
   * scope already has and queues them again, and sets `force` so the server
   * does the same.
   *
   * Needed because a plain generate silently queues nothing for a file that
   * already has a fix — `prepare_pending_fix` re-queues only a `failed` one —
   * so on the file engines a scope whose fixes are all written has to offer
   * this or offer nothing. See `isSpentFix`.
   */
  regenerate?: boolean
  /** Trigger requests currently in flight, by action. */
  pending?: Partial<Record<TargetActionId, boolean>>
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

/**
 * What this scope is busy with, from all three things that can know.
 *
 * The server's own answer (`activity`), the statuses this page happens to hold,
 * and any trigger request still in flight — unioned, then resolved by
 * `PRECEDENCE`. The middle one mirrors the backend's `activity_of`; the other
 * two are what a single derivation cannot see. Whichever says "busy" wins:
 * over-reporting costs a button that comes back a moment later, while
 * under-reporting is the race.
 */
export function targetActivity(input: EngineActionInput): TargetActivity {
  const found = new Set<TargetActivity>()
  if (input.activity && input.activity !== "idle") found.add(input.activity)
  if (asArray(input.scanStatus).some(isScanInFlight)) found.add("scanning")
  for (const status of input.fixStatuses ?? []) {
    if (status === "delivering") found.add("delivering")
    else if (status === "pending" || status === "generating") {
      found.add("generating")
    }
  }
  for (const [action, activity] of Object.entries(PENDING_ACTIVITY)) {
    if (input.pending?.[action as TargetActionId]) found.add(activity)
  }
  return PRECEDENCE.find((activity) => found.has(activity)) ?? "idle"
}

/**
 * Why `action` cannot run *right now*, or null — access, the enable flag, the
 * org's allowance, and whatever the target is busy with. Ordered widest-first:
 * an inaccessible repo, a disabled target and a spent allowance are standing
 * conditions worth saying before "something else is running", which is only
 * temporary.
 *
 * Deliberately says nothing about whether there is any work to do; that is the
 * caller's question and differs per button. Exported as
 * :func:`actionBlockedReason` for the actions that sit outside the bar —
 * removing a target, muting a finding, re-syncing a repository — which obey the
 * same conditions without being one of the three the bar draws.
 */
function blockedReason(
  action: TargetActionId,
  activity: TargetActivity,
  input: EngineActionInput,
): string | null {
  if (input.isAccessible === false) return NO_ACCESS_REASON
  if (input.enabled === false) {
    return `Enable this ${input.targetLabel.toLowerCase()} first`
  }
  const meter = METERS[action]
  if (meter) {
    const exhausted = input.quota?.[meter]
    if (exhausted) return exhausted
  }
  if (activity !== "idle" && BLOCKS[action].has(activity)) {
    return `Cannot ${VERBS[action]} while ${REASONS[activity]}`
  }
  return null
}

/** :func:`blockedReason` for a caller that has an input but no activity yet. */
export function actionBlockedReason(
  action: TargetActionId,
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
  // something they do not do. Discarding and re-queueing an existing fix is the
  // same endpoint with `force`, and belongs in the overflow menu rather than
  // hiding under a shared label.
  const noun = input.scope === "file" ? "fix" : "fixes"
  const verb = input.regenerate ? "Regenerate" : "Generate"
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
          : `${verb} ${noun}${countSuffix}`,
      icon: Wand2,
      busy: !!pending.generate || activity === "generating",
      disabled: !!generateBlocked || !!pending.generate || !hasFindings,
      reason:
        generateBlocked ??
        (hasFindings
          ? null
          : (input.noFindingsReason ?? "No open findings to fix")),
      force: !!input.regenerate,
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

/**
 * Removing a target, ready to render as an overflow item.
 *
 * Its own function rather than a fourth entry in `engineActions` because it is
 * destructive and belongs in a menu, not in the row — but the rule it obeys is
 * the same one, and the delete endpoints now enforce it: the cascade takes the
 * target's scans, findings and fixes with it, so a worker mid-write is a
 * refusal rather than a race.
 */
export function removeAction(input: EngineActionInput): EngineAction {
  const blocked = actionBlockedReason("remove", {
    ...input,
    // Removal needs no GitHub access and no enable flag: cleaning up a target
    // on a repository the App was uninstalled from is exactly when a user
    // reaches for it, and the DELETE has no such check either.
    isAccessible: undefined,
    enabled: undefined,
  })
  return {
    label: input.pending?.remove ? "Removing…" : "Remove",
    icon: Trash2,
    busy: !!input.pending?.remove,
    disabled: !!blocked || !!input.pending?.remove,
    reason: blocked,
    force: false,
  }
}

/**
 * Re-reading a repository's workflow files from GitHub.
 *
 * The CI engine's own action, and the only one outside the bar that touches
 * GitHub — so unlike `removeAction` it keeps the access check.
 */
export function syncAction(input: EngineActionInput): EngineAction {
  const blocked = actionBlockedReason("sync", input)
  return {
    label: input.pending?.sync ? "Syncing…" : "Sync from GitHub",
    icon: RefreshCw,
    busy: !!input.pending?.sync,
    disabled: !!blocked || !!input.pending?.sync,
    reason: blocked,
    force: false,
  }
}

/**
 * Muting or un-muting one finding.
 *
 * Two rules beyond the activity table. A **resolved** finding cannot be
 * ignored: `FindingMachine.ignore` is legal only from `open` and
 * `fix_in_progress`, so the request used to return the row unchanged while the
 * page toasted "Finding ignored" over a finding it had not ignored. And access
 * is deliberately not checked — muting is a database write with no GitHub call,
 * so a repository whose App access was lost is still the user's to triage.
 */
export function ignoreAction(
  status: FindingStatus | null | undefined,
  input: EngineActionInput,
): EngineAction {
  const ignored = status === "ignored"
  const blocked = actionBlockedReason("ignore", {
    ...input,
    isAccessible: undefined,
    enabled: undefined,
  })
  const resolved = !ignored && status === "resolved"
  const pending = !!input.pending?.ignore
  return {
    label: ignored ? "Unignore" : "Ignore",
    icon: ignored ? Bell : BellOff,
    busy: pending,
    disabled: !!blocked || pending || resolved,
    reason: blocked ?? (resolved ? "This finding is already resolved" : null),
    force: false,
  }
}

/**
 * Findings a "Generate fixes" button would actually queue something for.
 *
 * `prepare_pending_fix` creates or re-queues a file's fix only when the file
 * has none or its fix is `failed`; every other status returns `None` and the
 * route answers `202 {"queued": 0}`. So a target whose files all carry a
 * written fix had a live button that queued nothing and toasted "Fix
 * generation queued".
 *
 * A fix a worker still holds is deliberately *not* dropped: it queues nothing
 * either, but the button already says "Generating…" over a spinner, which is
 * the truthful account of that. `isSpentFix` draws the line.
 *
 * File engines only. The CI engine's batch endpoint deletes and recreates its
 * fixes first, so it has no such dead spot — which is why this is a helper the
 * file-engine pages call rather than a rule inside `engineActions`.
 */
export function queueableFindings<
  TFinding extends { file_path: string; status?: FindingStatus },
>(
  findings: readonly TFinding[],
  fixByFile: ReadonlyMap<string, { status: FixStatus }>,
): TFinding[] {
  return findings.filter((finding) => {
    if (finding.status === "ignored" || finding.status === "resolved") {
      return false
    }
    return !isSpentFix(fixByFile.get(finding.file_path)?.status)
  })
}

/**
 * What to say when a target has open findings but every one of their files is
 * already spoken for. Distinct from "No open findings to fix", which would read
 * as "there is nothing wrong here".
 */
/**
 * Whether a plain "Generate" on this file would queue nothing.
 *
 * `prepare_pending_fix` creates a fix for a file that has none and re-queues
 * one that is `failed`; every other status returns `None` unless the caller
 * forces. A fix that is in flight is not spent — it is being written — and the
 * activity table already refuses on that.
 */
export function isSpentFix(status: FixStatus | null | undefined): boolean {
  return status != null && status !== "failed" && !FIX_IN_FLIGHT.has(status)
}

export const ALREADY_FIXED_REASON =
  "Every file with findings already has a fix — regenerate it instead"

export type FixActionId = "deliver" | "retry" | "reject"

export interface FixActionInput {
  status: FixStatus | null | undefined
  /** The repo's GitHub App access. */
  isAccessible?: boolean
  /** What the fix's own scope (its file) is busy with. */
  activity?: TargetActivity
  /**
   * The delivery's label and force flag, from `lib/delivery`'s `deliverAction`.
   * `null` means this fix has no delivery to offer — the reason then comes from
   * its status.
   */
  delivery?: { label: string; force: boolean } | null
  pending?: Partial<Record<FixActionId, boolean>>
}

/**
 * Why a fix cannot be delivered, keyed by the status that says so.
 *
 * The rows are `FixMachine`'s: `start_delivery` is legal only from `ready`, and
 * `force` widens that to `{ready, delivered, failed}` — which `deliverAction`
 * already decides. Everything left here is a state with no way forward, and
 * saying which one is the difference between a greyed button and a mystery.
 */
const DELIVER_UNAVAILABLE: Partial<Record<FixStatus, string>> = {
  pending: "This fix has not been written yet",
  generating: "This fix is still being generated",
  delivering: "A pull request is already being opened for this fix",
  failed: "This fix failed to generate — retry it first",
  landed: "This fix has already been merged",
  no_op: "This rewrite changed nothing, so there is nothing to deliver",
  rejected_by_user: "This fix was rejected",
  superseded_by_closed_pr:
    "This fix was withdrawn when its pull request closed",
  superseded_by_deleted_file: "The file this fix targets was deleted",
}

/** Statuses `FixMachine.reject` has no edge from, and why. */
const REJECT_UNAVAILABLE: Partial<Record<FixStatus, string>> = {
  failed: "This fix already failed — there is nothing to reject",
  landed: "This fix has already been merged",
  no_op: "This fix was already withdrawn",
  rejected_by_user: "This fix is already rejected",
}

/**
 * The three things a single fix offers, ready to render.
 *
 * The fix detail page rendered these conditionally — Reject and Create PR only
 * on a `ready` fix, Retry only on a `failed` one — so a user looking at a
 * `no_op` fix saw an empty header and no account of why. They are all three
 * always drawn now, each carrying the sentence its status implies.
 *
 * `lib/delivery`'s `deliverAction` stays the authority on the delivery's label
 * and its `force` flag (it knows the one thing the status alone does not: a
 * withdrawn fix whose PR was closed can be reopened); this decides only whether
 * the button is live.
 */
export function fixActions(
  input: FixActionInput,
): Record<FixActionId, EngineAction> {
  const { status, delivery } = input
  const activity = input.activity ?? "idle"
  const pending = input.pending ?? {}
  const noAccess = input.isAccessible === false ? NO_ACCESS_REASON : null
  const missing = status == null ? "Generate a fix first" : null

  function gate(action: TargetActionId): string | null {
    if (missing) return missing
    if (noAccess) return noAccess
    if (activity !== "idle" && BLOCKS[action].has(activity)) {
      return `Cannot ${VERBS[action]} while ${REASONS[activity]}`
    }
    return null
  }

  const deliverBlocked =
    gate("deliver") ??
    (delivery ? null : ((status && DELIVER_UNAVAILABLE[status]) ?? null))
  // Retry maps onto `generate`: it re-queues the same row for the LLM, and the
  // route guards it with `TargetAction.generate` for exactly that reason.
  const retryBlocked =
    gate("generate") ??
    (status === "failed" ? null : "Only a failed fix can be retried")
  // Rejecting needs no GitHub call and collides with nothing a worker holds —
  // `FixMachine.reject` is legal from `delivering` — so it answers to its own
  // status alone.
  const rejectBlocked =
    missing ?? (status ? (REJECT_UNAVAILABLE[status] ?? null) : null)

  return {
    deliver: {
      label: pending.deliver ? "Queuing…" : (delivery?.label ?? "Create PR"),
      icon: GitPullRequest,
      busy: !!pending.deliver || status === "delivering",
      disabled: !!deliverBlocked || !!pending.deliver,
      reason: deliverBlocked,
      force: delivery?.force ?? false,
    },
    retry: {
      label: pending.retry ? "Retrying…" : "Retry",
      icon: RefreshCw,
      busy: !!pending.retry,
      disabled: !!retryBlocked || !!pending.retry,
      reason: retryBlocked,
      force: false,
    },
    reject: {
      label: pending.reject ? "Rejecting…" : "Reject",
      icon: Trash2,
      busy: !!pending.reject,
      disabled: !!rejectBlocked || !!pending.reject,
      reason: rejectBlocked,
      force: false,
    },
  }
}
