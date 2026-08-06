import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { GitPullRequest, Loader2, RefreshCw } from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import { toast } from "sonner"
import { FixesService, type FixPublic, type PullRequestPublic } from "@/client"
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
import {
  INTEGRATE_ACTION_BRANCH,
  repoFixBranch,
  workflowFixBranch,
} from "@/lib/delivery"
import {
  ciStatusColor,
  ciStatusLabel,
  mergeableIndicator,
  reviewDecisionColor,
  reviewDecisionLabel,
} from "@/lib/status-colors"
import { PAGE_SIZE, workflowLabel } from "@/lib/workflow-utils"
import { apiErrorDetail } from "@/utils"

export const Route = createFileRoute(
  "/_layout/repositories/$repoId/pull-requests",
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
  const { isAccessible } = useRepository(repoId)
  const [stateFilter, setStateFilter] = useState<string>("all")
  const [sortBy, setSortBy] = useState<"updated" | "created">("updated")
  const [page, setPage] = useState(0)

  const { data: pullRequests, isLoading } = useQuery({
    queryKey: ["pull-requests", "repo", repoId],
    queryFn: () => FixesService.listPullRequests({ repoId }),
  })

  // The fix set lets us name the workflow behind each PR branch and drive the
  // per-PR Update/Reopen (redeliver) action.
  const { data: fixes } = useQuery({
    queryKey: ["fixes", "repo", repoId],
    queryFn: () => FixesService.listFixes({ repoId, limit: 100 }),
  })

  const fixByBranch = useMemo(() => {
    const map = new Map<string, FixPublic>()
    for (const fix of fixes ?? []) {
      map.set(workflowFixBranch(fix.workflow_file_id), fix)
    }
    return map
  }, [fixes])

  const repoBranch = repoFixBranch(repoId)

  const syncMutation = useMutation({
    mutationFn: () => FixesService.syncPrStatuses({ repoId }),
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
      FixesService.triggerWorkflowDelivery({
        force: vars.force,
        requestBody: { fix_id: vars.fixId },
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
      FixesService.triggerRepoDelivery({ repoId, force: vars.force }),
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

  useEffect(() => {
    syncMutation.mutate()
  }, [syncMutation.mutate])

  const sorted = useMemo(() => {
    const key = sortBy === "created" ? "created_at" : "updated_at"
    return [...(pullRequests ?? [])].sort(
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

  // What Update/Reopen should do for a PR, and how to fire it. Merged PRs are
  // terminal; a workflow PR needs a still-deliverable fix behind its branch.
  function prAction(pr: PullRequestPublic): {
    label: string
    run: () => void
    pending: boolean
  } | null {
    const state = pr.pr_state ?? "open"
    if (state === "merged") return null
    const force = state === "closed"
    const label = state === "closed" ? "Reopen PR" : "Update PR"

    if (pr.pr_branch === repoBranch) {
      return {
        label,
        run: () => deliverRepoMutation.mutate({ force }),
        pending: deliverRepoMutation.isPending,
      }
    }
    const fix = fixByBranch.get(pr.pr_branch)
    if (!fix) return null
    return {
      label,
      run: () => deliverWorkflowMutation.mutate({ fixId: fix.id, force }),
      pending:
        deliverWorkflowMutation.isPending &&
        deliverWorkflowMutation.variables?.fixId === fix.id,
    }
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
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            disabled={syncMutation.isPending}
            onClick={() => syncMutation.mutate()}
            title="Sync PR statuses from GitHub"
          >
            <RefreshCw
              className={`h-3.5 w-3.5 ${syncMutation.isPending ? "animate-spin" : ""}`}
            />
          </Button>
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
                        : fixByBranch.get(pr.pr_branch)?.workflow_file_path
                          ? workflowLabel(
                              fixByBranch.get(pr.pr_branch)!
                                .workflow_file_path ?? "",
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
                        {action && (
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-7 text-xs gap-1.5 shrink-0"
                            onClick={action.run}
                            disabled={!isAccessible || action.pending}
                            title={
                              pr.externally_modified
                                ? "This branch has user commits; use force via the workflow card if needed"
                                : undefined
                            }
                          >
                            {action.pending ? (
                              <Loader2 className="h-3 w-3 animate-spin" />
                            ) : (
                              <GitPullRequest className="h-3 w-3" />
                            )}
                            {action.pending ? "Queuing…" : action.label}
                          </Button>
                        )}
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
