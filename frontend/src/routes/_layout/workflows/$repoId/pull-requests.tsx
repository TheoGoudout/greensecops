import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { GitPullRequest, RefreshCw } from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import { toast } from "sonner"
import {
  type PullRequestPublic,
  type WorkflowFixPublic,
  WorkflowService,
} from "@/client"
import { EngineActionButton } from "@/components/EngineActionBar"
import { StatusPill } from "@/components/StatusPill"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { useRepository } from "@/hooks/useRepository"
import { apiErrorDetail } from "@/lib/api-error"
import {
  INTEGRATE_ACTION_BRANCH,
  isWorkflowBranch,
  repoFixBranch,
  workflowFixBranch,
} from "@/lib/delivery"
import {
  actionBlockedReason,
  type EngineAction,
  type EngineActionInput,
  engineActions,
  isFixInFlight,
} from "@/lib/engine-actions"
import { SCAN_POLL_MS } from "@/lib/scan-polling"
import {
  ciStatusColor,
  ciStatusLabel,
  mergeableIndicator,
  reviewDecisionColor,
  reviewDecisionLabel,
} from "@/lib/status-colors"
import { PAGE_SIZE, workflowLabel } from "@/lib/workflow-utils"

export const Route = createFileRoute(
  "/_layout/workflows/$repoId/pull-requests",
)({
  component: PullRequestsPage,
  head: () => ({
    meta: [{ title: "PRs - GreenSecOps" }],
  }),
})

const STATE_CLASSES: Record<string, string> = {
  merged: "bg-purple-500/15 text-purple-700 dark:text-purple-400",
  closed: "bg-red-500/15 text-red-700 dark:text-red-400",
  draft: "bg-muted text-muted-foreground",
  open: "bg-green-500/15 text-green-700 dark:text-green-400",
}

function PullRequestsPage() {
  const { repoId } = Route.useParams()
  const queryClient = useQueryClient()
  const { repo, isAccessible } = useRepository(repoId)
  const [stateFilter, setStateFilter] = useState<string>("all")
  const [sortBy, setSortBy] = useState<"updated" | "created">("updated")
  const [page, setPage] = useState(0)

  const { data: pullRequests, isLoading } = useQuery({
    queryKey: ["pull-requests", "repo", repoId],
    queryFn: () => WorkflowService.listPullRequests({ repoId }),
  })

  // The fix set lets us name the workflow behind each PR branch and drive the
  // per-PR Update/Reopen (redeliver) action.
  const { data: fixes } = useQuery({
    queryKey: ["fixes", "repo", repoId],
    queryFn: () => WorkflowService.listFixes({ repoId, limit: 100 }),
    // A delivery queued from this page is what greys these buttons; without a
    // poll they stayed grey until a reload.
    refetchInterval: (query) =>
      (query.state.data ?? []).some((f) => isFixInFlight(f.status))
        ? SCAN_POLL_MS
        : false,
  })

  // The analyses this repository is running. A CI analysis holds a repo-wide
  // lock and refuses every delivery under it, so the buttons below have to see
  // it — this page never asked.
  const { data: analyses } = useQuery({
    queryKey: ["scans", repoId],
    queryFn: () => WorkflowService.listScans({ repoId, limit: 100 }),
  })

  const repoState: EngineActionInput = {
    targetLabel: "repository",
    scope: "repo",
    isAccessible,
    activity: repo?.activity,
    scanStatus: (analyses ?? []).map((a) => a.status),
  }

  // Why `deliver` rather than `sync`: this re-reads GitHub's view of the
  // repository's pull requests and writes it back onto the `pull_request`
  // rows — which is exactly what a delivery in flight is creating. It does not
  // take the analysis lock, so `sync`'s rule (refused by a scan alone) is the
  // wrong one; `deliver`'s names the activity that actually collides. That it
  // also stands down during a scan or a generation is a moment's wait on a
  // refresh nobody asked for, which is the cheaper mistake.
  const syncBlocked = actionBlockedReason("deliver", repoState)

  const fixByBranch = useMemo(() => {
    const map = new Map<string, WorkflowFixPublic>()
    for (const fix of fixes ?? []) {
      map.set(workflowFixBranch(fix.workflow_file_id), fix)
    }
    return map
  }, [fixes])

  const repoBranch = repoFixBranch(repoId)

  const syncMutation = useMutation({
    mutationFn: () => WorkflowService.syncPullRequestStatuses({ repoId }),
    onSuccess: (data: Record<string, number>) => {
      if (data.updated > 0 || data.relinked > 0) {
        queryClient.invalidateQueries({
          queryKey: ["pull-requests", "repo", repoId],
        })
      }
    },
  })

  const deliverWorkflowMutation = useMutation({
    mutationFn: (vars: { fixId: string; force: boolean }) =>
      WorkflowService.deliverFix({
        fixId: vars.fixId,
        force: vars.force,
      }),
    onSuccess: () => {
      toast.success("Pull request update queued")
      queryClient.invalidateQueries({
        queryKey: ["pull-requests", "repo", repoId],
      })
      queryClient.invalidateQueries({ queryKey: ["fixes", "repo", repoId] })
    },
    onError: (error) =>
      toast.error("Failed to update PR", {
        description: apiErrorDetail(error),
      }),
  })

  const deliverRepoMutation = useMutation({
    mutationFn: (vars: { force: boolean }) =>
      WorkflowService.deliverRepositoryFixes({ repoId, force: vars.force }),
    onSuccess: () => {
      toast.success("Pull request update queued")
      queryClient.invalidateQueries({
        queryKey: ["pull-requests", "repo", repoId],
      })
      queryClient.invalidateQueries({ queryKey: ["fixes", "repo", repoId] })
    },
    onError: (error) =>
      toast.error("Failed to update PR", {
        description: apiErrorDetail(error),
      }),
  })

  // Re-reading the PR statuses on arrival, but only when nothing is writing
  // them. It is a write the user did not ask for, fired from a mount effect,
  // and it lands on the same `pull_request` rows a delivery is creating — so
  // during one it would race the worker and then report what it raced. Idle is
  // the only state in which an unrequested refresh is a refresh.
  const canAutoSync = !syncBlocked
  useEffect(() => {
    if (canAutoSync) syncMutation.mutate()
  }, [canAutoSync, syncMutation.mutate])

  const sorted = useMemo(() => {
    const key = sortBy === "created" ? "created_at" : "updated_at"
    return (pullRequests ?? [])
      .filter((pr) => isWorkflowBranch(pr.pr_branch))
      .sort(
        (a, b) =>
          new Date(b[key] ?? b.created_at ?? 0).getTime() -
          new Date(a[key] ?? a.created_at ?? 0).getTime(),
      )
  }, [pullRequests, sortBy])

  const filtered = useMemo(() => {
    if (stateFilter === "all") return sorted
    return sorted.filter((pr) => (pr.pr_state ?? "open") === stateFilter)
  }, [sorted, stateFilter])

  const paged = useMemo(
    () => filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE),
    [filtered, page],
  )

  // What Update/Reopen may do for a PR, and how to fire it.
  //
  // The two states this row knows and the shared rules do not are the PR's own:
  // a merged PR is finished, and a branch with no fix behind it has nothing to
  // redeliver from. Both used to return `null` and take the button away with
  // them; they are reasons now, and everything else — a running analysis, a fix
  // still being written, lost access — comes from the same table every other
  // delivery button obeys.
  function prAction(pr: PullRequestPublic): {
    action: EngineAction
    run: () => void
  } {
    const state = pr.pr_state ?? "open"
    const force = state === "closed"
    const isRepoWide = pr.pr_branch === repoBranch
    const fix = isRepoWide ? undefined : fixByBranch.get(pr.pr_branch)
    const pending = isRepoWide
      ? deliverRepoMutation.isPending
      : deliverWorkflowMutation.isPending &&
        deliverWorkflowMutation.variables?.fixId === fix?.id

    const action = engineActions({
      ...repoState,
      // A repo-wide PR is delivered from every fix in the repository; a
      // per-workflow one only from its own, so one file's generation must not
      // freeze another file's PR.
      fixStatuses: isRepoWide
        ? (fixes ?? []).map((f) => f.status)
        : fix
          ? [fix.status]
          : [],
      existingPr: pr,
      // Redelivery does not need a `ready` fix the way a first delivery does:
      // `force` widens the worker's selection to the fixes already delivered,
      // which is what updating an open PR means.
      reopenable: true,
      pending: { deliver: pending },
    }).deliver

    const run = () =>
      isRepoWide
        ? deliverRepoMutation.mutate({ force })
        : fix && deliverWorkflowMutation.mutate({ fixId: fix.id, force })

    if (state === "merged") {
      return {
        run,
        action: {
          ...action,
          disabled: true,
          reason: "This pull request has been merged",
        },
      }
    }
    if (!isRepoWide && !fix) {
      return {
        run,
        action: {
          ...action,
          disabled: true,
          reason: "No fix on this branch to redeliver",
        },
      }
    }
    return { action, run }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-2">
          <Select
            value={stateFilter}
            onValueChange={(v) => {
              setStateFilter(v)
              setPage(0)
            }}
          >
            <SelectTrigger className="w-32 h-8 text-xs">
              <SelectValue placeholder="State" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All states</SelectItem>
              <SelectItem value="open">Open</SelectItem>
              <SelectItem value="draft">Draft</SelectItem>
              <SelectItem value="closed">Closed</SelectItem>
              <SelectItem value="merged">Merged</SelectItem>
            </SelectContent>
          </Select>
          <Select
            value={sortBy}
            onValueChange={(v) => setSortBy(v as "updated" | "created")}
          >
            <SelectTrigger className="w-36 h-8 text-xs">
              <SelectValue placeholder="Sort" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="updated">Recently updated</SelectItem>
              <SelectItem value="created">Recently created</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="flex items-center gap-2">
          {/* Reading GitHub's view of these PRs back. Deliberately *not* the
              `sync` action: that one re-reads the workflow files and takes the
              analysis lock, while this only refreshes PR state, so a running
              analysis is no reason to refuse it. Lost access is. */}
          <EngineActionButton
            variant="ghost"
            compact
            action={{
              label: syncMutation.isPending ? "Syncing…" : "Sync",
              icon: RefreshCw,
              busy: syncMutation.isPending,
              disabled: !!syncBlocked || syncMutation.isPending,
              reason: syncBlocked,
              force: false,
            }}
            onClick={() => syncMutation.mutate()}
          />
          <span className="text-xs text-muted-foreground">
            {filtered.length} PR{filtered.length !== 1 ? "s" : ""}
          </span>
        </div>
      </div>
      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="flex flex-col gap-2 p-6">
              {[...Array(4)].map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : filtered.length === 0 ? (
            <p className="text-sm text-muted-foreground p-6 text-center">
              {stateFilter === "all"
                ? "No GreenSecOps-created PRs yet. Generate and deliver fixes to see them here."
                : `No ${stateFilter} PRs.`}
            </p>
          ) : (
            <>
              <div className="divide-y">
                {paged.map((pr) => {
                  const state = pr.pr_state ?? "open"
                  const lastActivity = pr.updated_at ?? pr.created_at
                  const wfName =
                    pr.pr_branch === repoBranch
                      ? "All workflows"
                      : pr.pr_branch === INTEGRATE_ACTION_BRANCH
                        ? "Integrate action"
                        : fixByBranch.get(pr.pr_branch)?.file_path
                          ? workflowLabel(
                              fixByBranch.get(pr.pr_branch)!.file_path ?? "",
                            )
                          : null
                  const mergeable = mergeableIndicator(pr.mergeable_state)
                  const action = prAction(pr)
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
                          {wfName && (
                            <>
                              <span className="font-mono truncate">
                                {wfName}
                              </span>
                              <span className="shrink-0">—</span>
                            </>
                          )}
                          {pr.ci_status && pr.ci_status !== "none" && (
                            <StatusPill
                              colorClass={ciStatusColor(pr.ci_status)}
                            >
                              {ciStatusLabel(pr.ci_status)}
                            </StatusPill>
                          )}
                          {pr.review_decision && (
                            <StatusPill
                              colorClass={reviewDecisionColor(
                                pr.review_decision,
                              )}
                            >
                              {reviewDecisionLabel(pr.review_decision)}
                            </StatusPill>
                          )}
                          {mergeable && (
                            <span
                              className={`px-1.5 py-0.5 rounded-full font-medium ${mergeable.cls}`}
                            >
                              {mergeable.label}
                            </span>
                          )}
                          {pr.externally_modified && (
                            <span
                              className="px-1.5 py-0.5 rounded-full bg-amber-500/15 text-amber-700 dark:text-amber-400"
                              title="A user pushed commits to this fix branch; automatic redelivery is paused"
                            >
                              user-edited
                            </span>
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
                          action={action.action}
                          compact
                          onClick={action.run}
                        />
                      </div>
                    </div>
                  )
                })}
              </div>
              {filtered.length > PAGE_SIZE && (
                <div className="flex items-center justify-between px-6 py-3 border-t">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={page === 0}
                    onClick={() => setPage((p) => p - 1)}
                  >
                    Previous
                  </Button>
                  <span className="text-xs text-muted-foreground">
                    Page {page + 1} of {Math.ceil(filtered.length / PAGE_SIZE)}
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={(page + 1) * PAGE_SIZE >= filtered.length}
                    onClick={() => setPage((p) => p + 1)}
                  >
                    Next
                  </Button>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
