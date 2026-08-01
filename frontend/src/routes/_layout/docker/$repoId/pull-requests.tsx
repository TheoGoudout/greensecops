import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { GitPullRequest, Loader2 } from "lucide-react"
import { useMemo } from "react"
import { toast } from "sonner"
import type { DockerTargetPublic } from "@/client"
import { DockerService, FixesService } from "@/client"
import { StatusPill } from "@/components/StatusPill"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { dockerFixBranch } from "@/lib/delivery"
import {
  ciStatusColor,
  ciStatusLabel,
  reviewDecisionColor,
  reviewDecisionLabel,
} from "@/lib/status-colors"
import { apiErrorDetail } from "@/utils"

export const Route = createFileRoute("/_layout/docker/$repoId/pull-requests")({
  component: DockerPullRequestsTab,
  head: () => ({
    meta: [{ title: "Docker PRs - GreenSecOps" }],
  }),
})

const STATE_CLASSES: Record<string, string> = {
  merged: "bg-purple-500/15 text-purple-700 dark:text-purple-400",
  closed: "bg-red-500/15 text-red-700 dark:text-red-400",
  draft: "bg-muted text-muted-foreground",
  open: "bg-green-500/15 text-green-700 dark:text-green-400",
}

// Docker PR branches carry a distinct prefix; this tab only lists those,
// keeping Terraform and CI-workflow fix PRs on their own pages.
const DOCKER_BRANCH_PREFIX = "greensecops/docker-"

function DockerPullRequestsTab() {
  const { repoId } = Route.useParams()
  const queryClient = useQueryClient()

  const { data: pullRequests, isLoading } = useQuery({
    queryKey: ["pull-requests", "repo", repoId],
    queryFn: () => FixesService.listPullRequests({ repoId }),
  })

  const { data: targets } = useQuery({
    queryKey: ["docker-targets", "repo", repoId],
    queryFn: () => DockerService.listDockerTargets({ repoId }),
  })

  // Map a Docker PR branch back to the target that owns it, so "Update PR"
  // can redeliver that target's fixes.
  const targetByBranch = useMemo(() => {
    const map = new Map<string, DockerTargetPublic>()
    for (const target of targets ?? [])
      map.set(dockerFixBranch(target.id), target)
    return map
  }, [targets])

  const dockerPrs = useMemo(
    () =>
      (pullRequests ?? [])
        .filter((pr) => pr.pr_branch.startsWith(DOCKER_BRANCH_PREFIX))
        .sort(
          (a, b) =>
            new Date(b.updated_at ?? b.created_at ?? 0).getTime() -
            new Date(a.updated_at ?? a.created_at ?? 0).getTime(),
        ),
    [pullRequests],
  )

  const deliverMutation = useMutation({
    mutationFn: (vars: { targetId: string; force: boolean }) =>
      DockerService.triggerDockerDelivery({
        targetId: vars.targetId,
        force: vars.force,
      }),
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
        ) : dockerPrs.length === 0 ? (
          <p className="text-sm text-muted-foreground p-6 text-center">
            No Docker PRs yet. Generate and deliver fixes from the{" "}
            <span className="font-medium">Analysis</span> tab to see them here.
          </p>
        ) : (
          <div className="divide-y">
            {dockerPrs.map((pr) => {
              const state = pr.pr_state ?? "open"
              const lastActivity = pr.updated_at ?? pr.created_at
              const target = targetByBranch.get(pr.pr_branch)
              const canRedeliver = target && state !== "merged"
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
