import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { GitPullRequest, Loader2 } from "lucide-react"
import { useMemo } from "react"
import { toast } from "sonner"
import type { TerraformRootPublic } from "@/client"
import { FixesService, TerraformService } from "@/client"
import { StatusPill } from "@/components/StatusPill"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { tfFixBranch } from "@/lib/delivery"
import {
  ciStatusColor,
  ciStatusLabel,
  reviewDecisionColor,
  reviewDecisionLabel,
} from "@/lib/status-colors"
import { apiErrorDetail } from "@/utils"

export const Route = createFileRoute(
  "/_layout/infrastructure/$repoId/pull-requests",
)({
  component: TerraformPullRequestsTab,
  head: () => ({
    meta: [{ title: "Terraform PRs - GreenSecOps" }],
  }),
})

const STATE_CLASSES: Record<string, string> = {
  merged: "bg-purple-500/15 text-purple-700 dark:text-purple-400",
  closed: "bg-red-500/15 text-red-700 dark:text-red-400",
  draft: "bg-muted text-muted-foreground",
  open: "bg-green-500/15 text-green-700 dark:text-green-400",
}

// Terraform PR branches carry a distinct prefix; the Infrastructure PRs tab
// only lists those, keeping CI-workflow fix PRs on the Repositories page.
const TF_BRANCH_PREFIX = "greensecops/terraform-"

function TerraformPullRequestsTab() {
  const { repoId } = Route.useParams()
  const queryClient = useQueryClient()

  const { data: pullRequests, isLoading } = useQuery({
    queryKey: ["pull-requests", "repo", repoId],
    queryFn: () => FixesService.listPullRequests({ repoId }),
  })

  const { data: roots } = useQuery({
    queryKey: ["terraform-roots", "repo", repoId],
    queryFn: () => TerraformService.listTerraformRoots({ repoId }),
  })

  // Map a Terraform PR branch back to the root that owns it, so "Update PR"
  // can redeliver that root's fixes.
  const rootByBranch = useMemo(() => {
    const map = new Map<string, TerraformRootPublic>()
    for (const root of roots ?? []) map.set(tfFixBranch(root.id), root)
    return map
  }, [roots])

  const terraformPrs = useMemo(
    () =>
      (pullRequests ?? [])
        .filter((pr) => pr.pr_branch.startsWith(TF_BRANCH_PREFIX))
        .sort(
          (a, b) =>
            new Date(b.updated_at ?? b.created_at ?? 0).getTime() -
            new Date(a.updated_at ?? a.created_at ?? 0).getTime(),
        ),
    [pullRequests],
  )

  const deliverMutation = useMutation({
    mutationFn: (vars: { rootId: string; force: boolean }) =>
      TerraformService.triggerTerraformDelivery({
        rootId: vars.rootId,
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
        ) : terraformPrs.length === 0 ? (
          <p className="text-sm text-muted-foreground p-6 text-center">
            No Terraform PRs yet. Generate and deliver fixes from the{" "}
            <span className="font-medium">Terraform</span> tab to see them here.
          </p>
        ) : (
          <div className="divide-y">
            {terraformPrs.map((pr) => {
              const state = pr.pr_state ?? "open"
              const lastActivity = pr.updated_at ?? pr.created_at
              const root = rootByBranch.get(pr.pr_branch)
              const canRedeliver = root && state !== "merged"
              const force = state === "closed"
              const isPending =
                deliverMutation.isPending &&
                deliverMutation.variables?.rootId === root?.id
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
                      {root && (
                        <>
                          <span className="font-mono truncate">
                            {root.root_path}
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
                          deliverMutation.mutate({ rootId: root.id, force })
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
