import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { GitPullRequest } from "lucide-react"
import { useMemo } from "react"
import { toast } from "sonner"
import type { FixStatus, PullRequestPublic, ScanStatus } from "@/client"
import { WorkflowService } from "@/client"
import { EngineActionButton } from "@/components/EngineActionBar"
import { StatusPill } from "@/components/StatusPill"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { apiErrorDetail } from "@/lib/api-error"
import { engineActions, isFixInFlight } from "@/lib/engine-actions"
import { SCAN_POLL_MS } from "@/lib/scan-polling"
import {
  ciStatusColor,
  ciStatusLabel,
  reviewDecisionColor,
  reviewDecisionLabel,
} from "@/lib/status-colors"

const STATE_CLASSES: Record<string, string> = {
  merged: "bg-purple-500/15 text-purple-700 dark:text-purple-400",
  closed: "bg-red-500/15 text-red-700 dark:text-red-400",
  draft: "bg-muted text-muted-foreground",
  open: "bg-green-500/15 text-green-700 dark:text-green-400",
}

/** The minimum a scan target needs to be listed and redelivered here. */
interface Target {
  id: string
  root_path: string
  enabled: boolean
  latest_scan_status?: ScanStatus | null
}

/** The minimum a fix needs for the activity rules. */
interface Fix {
  status: FixStatus
}

interface EnginePullRequestsTabProps {
  repoId: string
  /** Human name of the engine, for the empty state. */
  label: string
  /**
   * Branch prefix identifying this engine's PRs. Each engine mints its own
   * (`greensecops/docker-`, `greensecops/terraform-`), which is what lets a
   * repo's PRs be split across tabs by branch name alone.
   */
  branchPrefix: string
  /** The engine's scan targets, and the branch each one's PR uses. */
  targets: Target[] | undefined
  branchForTarget: (targetId: string) => string
  /**
   * Tab the reader should go to in order to produce these PRs. Defaults to
   * "Analysis" — the name Terraform and Docker both use — but the Ansible
   * engine's analysis lives on a tab named after the engine itself, and
   * pointing someone at a tab that isn't there is worse than no hint.
   */
  sourceTabLabel?: string
  /** Re-run delivery for a target, updating (or reopening) its PR. */
  deliver: (vars: { targetId: string; force: boolean }) => Promise<unknown>
  /** The repo's GitHub App access — a delivery is a push, so it needs it. */
  isAccessible?: boolean
  /**
   * Every fix under this repository's targets, and which target each belongs
   * to.
   *
   * "Update PR" is a delivery, and a delivery is refused while the target is
   * scanning, generating or already delivering. This tab could not see any of
   * that: it knew the PRs and the targets but never the fixes, so the button
   * stayed live through all three and the click 409'd. The engines'
   * cross-target `GET /{engine}/fixes` exists for this.
   */
  keyPrefix: string
  listFixes: () => Promise<Fix[]>
  targetIdOfFix: (fix: Fix) => string
}

/**
 * Whether one PR row's "Update PR" may be pressed, and what to say if not.
 *
 * Redelivery is a delivery: the same table that refuses one on a scanning,
 * generating or delivering target refuses it here, and this row had none of
 * that — it checked only whether its own request was in flight. The two states
 * the shared rules cannot know about are the PR's own: a merged one is
 * finished, and a branch whose target has since been removed has nothing left
 * to deliver from. Both are drawn greyed rather than dropped, so a reader is
 * told why the row they are looking at has no action.
 */
function redeliverAction({
  pr,
  target,
  isAccessible,
  fixStatuses,
  pending,
}: {
  pr: PullRequestPublic
  target: Target | undefined
  isAccessible: boolean
  fixStatuses: readonly FixStatus[]
  pending: boolean
}) {
  const state = pr.pr_state ?? "open"
  const action = engineActions({
    targetLabel: target ? "target" : "pull request",
    scope: "target",
    isAccessible,
    enabled: target?.enabled,
    scanStatus: target?.latest_scan_status,
    fixStatuses,
    existingPr: pr,
    // Redelivery does not need a `ready` fix the way a first delivery does:
    // `force` widens the worker's selection to the fixes already delivered,
    // which is exactly what updating an open PR means.
    reopenable: true,
    pending: { deliver: pending },
  }).deliver
  if (!target) {
    return {
      ...action,
      disabled: true,
      reason: "No target on this branch to redeliver from",
    }
  }
  if (state === "merged") {
    return {
      ...action,
      disabled: true,
      reason: "This pull request has been merged",
    }
  }
  return action
}

/**
 * The pull requests one engine has opened against a repository.
 *
 * Shared by the Docker and Infrastructure tabs, which were the same component
 * with the nouns swapped. The CI-workflow tab is deliberately not folded in:
 * it also offers per-workflow filtering and a mergeable-state indicator, so it
 * is a superset rather than the same page.
 */
export function EnginePullRequestsTab({
  repoId,
  label,
  branchPrefix,
  targets,
  branchForTarget,
  deliver,
  isAccessible = true,
  keyPrefix,
  listFixes,
  targetIdOfFix,
  sourceTabLabel = "Analysis",
}: EnginePullRequestsTabProps) {
  const queryClient = useQueryClient()

  const { data: fixes } = useQuery({
    queryKey: [`${keyPrefix}-repo-fixes`, repoId],
    queryFn: listFixes,
    // A delivery queued from here is what greys these buttons; without a poll
    // they stayed grey until a reload.
    refetchInterval: (query) =>
      (query.state.data ?? []).some((f) => isFixInFlight(f.status))
        ? SCAN_POLL_MS
        : false,
  })

  const fixesByTarget = useMemo(() => {
    const map = new Map<string, FixStatus[]>()
    for (const fix of fixes ?? []) {
      const id = targetIdOfFix(fix)
      map.set(id, [...(map.get(id) ?? []), fix.status])
    }
    return map
  }, [fixes, targetIdOfFix])

  const { data: pullRequests, isLoading } = useQuery({
    queryKey: ["pull-requests", "repo", repoId],
    queryFn: () => WorkflowService.listPullRequests({ repoId }),
  })

  // Map a PR branch back to the target that owns it, so "Update PR" can
  // redeliver that target's fixes.
  const targetByBranch = useMemo(() => {
    const map = new Map<string, Target>()
    for (const target of targets ?? [])
      map.set(branchForTarget(target.id), target)
    return map
  }, [targets, branchForTarget])

  const prs = useMemo(
    () =>
      (pullRequests ?? [])
        .filter((pr) => pr.pr_branch.startsWith(branchPrefix))
        .sort(
          (a, b) =>
            new Date(b.updated_at ?? b.created_at ?? 0).getTime() -
            new Date(a.updated_at ?? a.created_at ?? 0).getTime(),
        ),
    [pullRequests, branchPrefix],
  )

  const deliverMutation = useMutation({
    mutationFn: deliver,
    onSuccess: () => {
      toast.success("Pull request update queued")
      queryClient.invalidateQueries({
        queryKey: ["pull-requests", "repo", repoId],
      })
      queryClient.invalidateQueries({ queryKey: [`${keyPrefix}-repo-fixes`] })
      queryClient.invalidateQueries({ queryKey: [`${keyPrefix}-fixes`] })
    },
    onError: (error) =>
      toast.error("Failed to update PR", {
        description: apiErrorDetail(error),
      }),
  })

  return (
    <Card>
      <CardContent className="p-0">
        {isLoading ? (
          <div className="flex flex-col gap-2 p-6">
            {[...Array(3)].map((_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : prs.length === 0 ? (
          <p className="text-sm text-muted-foreground p-6 text-center">
            No {label} PRs yet. Generate and deliver fixes from the{" "}
            <span className="font-medium">{sourceTabLabel}</span> tab to see
            them here.
          </p>
        ) : (
          <div className="divide-y">
            {prs.map((pr) => {
              const state = pr.pr_state ?? "open"
              const lastActivity = pr.updated_at ?? pr.created_at
              const target = targetByBranch.get(pr.pr_branch)
              // A closed PR needs the delivery forced to reopen it; a merged
              // one is finished, and a branch whose target is gone has nothing
              // to redeliver from. Both are said rather than hidden.
              const force = state === "closed"
              const isPending =
                deliverMutation.isPending &&
                deliverMutation.variables?.targetId === target?.id
              const action = redeliverAction({
                pr,
                target,
                isAccessible,
                fixStatuses: target ? (fixesByTarget.get(target.id) ?? []) : [],
                pending: isPending,
              })
              return (
                <div
                  key={pr.id}
                  className="flex flex-col gap-2 px-4 sm:px-6 py-3"
                >
                  <div className="flex items-center justify-between gap-3">
                    {pr.pr_url ? (
                      <a
                        href={pr.pr_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-xs font-mono text-blue-600 dark:text-blue-400 hover:underline truncate flex items-center gap-1.5 min-w-0"
                      >
                        <GitPullRequest className="h-3 w-3 shrink-0" />
                        {pr.pr_url.replace("https://github.com/", "")}
                      </a>
                    ) : (
                      <span className="text-xs font-mono text-muted-foreground truncate flex items-center gap-1.5 min-w-0">
                        <GitPullRequest className="h-3 w-3 shrink-0" />
                        {pr.pr_branch}
                      </span>
                    )}
                    <span
                      className={`text-xs font-medium px-2 py-0.5 rounded-full capitalize shrink-0 ${
                        STATE_CLASSES[state] ?? STATE_CLASSES.open
                      }`}
                    >
                      {state}
                    </span>
                  </div>
                  <div className="flex items-center justify-between gap-3 flex-wrap">
                    <div className="flex items-center gap-2 flex-wrap text-xs text-muted-foreground min-w-0">
                      {target && (
                        <>
                          <span className="font-mono truncate">
                            {target.root_path || "/"}
                          </span>
                          <span className="shrink-0">—</span>
                        </>
                      )}
                      {pr.ci_status && pr.ci_status !== "none" && (
                        <StatusPill colorClass={ciStatusColor(pr.ci_status)}>
                          {ciStatusLabel(pr.ci_status)}
                        </StatusPill>
                      )}
                      {pr.review_decision && (
                        <StatusPill
                          colorClass={reviewDecisionColor(pr.review_decision)}
                        >
                          {reviewDecisionLabel(pr.review_decision)}
                        </StatusPill>
                      )}
                      <span className="tabular-nums whitespace-nowrap">
                        {lastActivity
                          ? new Date(lastActivity).toLocaleDateString(
                              undefined,
                              {
                                month: "short",
                                day: "numeric",
                                hour: "2-digit",
                                minute: "2-digit",
                              },
                            )
                          : "—"}
                      </span>
                    </div>
                    <EngineActionButton
                      action={action}
                      compact
                      onClick={() =>
                        target &&
                        deliverMutation.mutate({ targetId: target.id, force })
                      }
                    />
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
