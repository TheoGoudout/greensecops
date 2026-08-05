import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { GitPullRequest, Loader2 } from "lucide-react"
import { useMemo } from "react"
import { toast } from "sonner"
import { FixesService } from "@/client"
import { StatusPill } from "@/components/StatusPill"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import {
  ciStatusColor,
  ciStatusLabel,
  reviewDecisionColor,
  reviewDecisionLabel,
} from "@/lib/status-colors"
import { apiErrorDetail } from "@/utils"

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
  /** Re-run delivery for a target, updating (or reopening) its PR. */
  deliver: (vars: { targetId: string; force: boolean }) => Promise<unknown>
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
}: EnginePullRequestsTabProps) {
  const queryClient = useQueryClient()

  const { data: pullRequests, isLoading } = useQuery({
    queryKey: ["pull-requests", "repo", repoId],
    queryFn: () => FixesService.listPullRequests({ repoId }),
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
            <span className="font-medium">Analysis</span> tab to see them here.
          </p>
        ) : (
          <div className="divide-y">
            {prs.map((pr) => {
              const state = pr.pr_state ?? "open"
              const lastActivity = pr.updated_at ?? pr.created_at
              const target = targetByBranch.get(pr.pr_branch)
              const canRedeliver = target && state !== "merged"
              // A closed PR needs the delivery forced to reopen it.
              const force = state === "closed"
              const isPending =
                deliverMutation.isPending &&
                deliverMutation.variables?.targetId === target?.id
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
                    {canRedeliver && (
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-7 text-xs gap-1.5 shrink-0"
                        onClick={() =>
                          deliverMutation.mutate({
                            targetId: target.id,
                            force,
                          })
                        }
                        disabled={isPending}
                      >
                        {isPending ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : (
                          <GitPullRequest className="h-3 w-3" />
                        )}
                        {isPending
                          ? "Queuing…"
                          : force
                            ? "Reopen PR"
                            : "Update PR"}
                      </Button>
                    )}
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
