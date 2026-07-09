import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { GitPullRequest, RefreshCw } from "lucide-react"
import { useMemo, useState } from "react"
import { toast } from "sonner"
import { FixesService } from "@/client"
import { CategoryIcon } from "@/components/CategoryIcon"
import { SeverityChip } from "@/components/SeverityChip"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { fixStatusColor } from "@/lib/status-colors"
import { PAGE_SIZE, workflowLabel } from "@/lib/workflow-utils"
import { apiErrorDetail } from "@/utils"

export const Route = createFileRoute("/_layout/repositories/$repoId/fixes")({
  component: FixesPage,
  head: () => ({
    meta: [{ title: "Fixes - GreenSecOps" }],
  }),
})

function FixesPage() {
  const { repoId } = Route.useParams()
  const queryClient = useQueryClient()
  const [fixesPage, setFixesPage] = useState(0)

  const { data: fixes, isLoading: fixesLoading } = useQuery({
    queryKey: ["fixes", "repo", repoId],
    queryFn: () => FixesService.listFixes({ repoId, limit: 100 }),
  })

  const deliverWorkflowMutation = useMutation({
    mutationFn: (fixId: string) =>
      FixesService.triggerWorkflowDelivery({
        requestBody: { fix_id: fixId },
      }),
    onSuccess: () => {
      toast.success("Workflow PR queued")
      queryClient.invalidateQueries({ queryKey: ["fixes", "repo", repoId] })
    },
    onError: (error) =>
      toast.error("Failed to queue workflow PR", {
        description: apiErrorDetail(error),
      }),
  })

  const deliverRepoMutation = useMutation({
    mutationFn: () => FixesService.triggerRepoDelivery({ repoId }),
    onSuccess: () => {
      toast.success("Repo-wide PR queued")
      queryClient.invalidateQueries({ queryKey: ["fixes", "repo", repoId] })
    },
    onError: (error) =>
      toast.error("Failed to queue repo-wide PR", {
        description: apiErrorDetail(error),
      }),
  })

  const regenerateMutation = useMutation({
    mutationFn: (prId: string) => FixesService.regenerateFixesForPr({ prId }),
    onSuccess: () => {
      toast.success("Fixes queued for regeneration")
      queryClient.invalidateQueries({ queryKey: ["fixes", "repo", repoId] })
    },
    onError: () => toast.error("Failed to regenerate fixes"),
  })

  const pagedFixes = useMemo(
    () =>
      (fixes ?? []).slice(fixesPage * PAGE_SIZE, (fixesPage + 1) * PAGE_SIZE),
    [fixes, fixesPage],
  )

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-4">
        {fixes?.some((f) => f.status === "ready") && (
          <Button
            size="sm"
            variant="outline"
            className="gap-2"
            onClick={() => deliverRepoMutation.mutate()}
            disabled={deliverRepoMutation.isPending}
          >
            <GitPullRequest className="h-4 w-4" />
            {deliverRepoMutation.isPending
              ? "Queuing…"
              : "Create PR for all workflows"}
          </Button>
        )}
      </div>

      <div className="flex flex-col gap-4">
        {fixesLoading ? (
          <div className="flex flex-col gap-2">
            {[...Array(4)].map((_, i) => (
              <Skeleton key={i} className="h-14 w-full" />
            ))}
          </div>
        ) : !fixes?.length ? (
          <Card>
            <CardContent className="py-8 text-center text-muted-foreground text-sm">
              No fixes yet.
            </CardContent>
          </Card>
        ) : (
          <>
            {pagedFixes.map((fix) => {
              const issues = fix.issues ?? []
              const isWfDelivering =
                deliverWorkflowMutation.isPending &&
                deliverWorkflowMutation.variables === fix.id
              const isRegenerating =
                regenerateMutation.isPending &&
                regenerateMutation.variables === fix.pr_id
              return (
                <Card key={fix.id}>
                  <CardHeader className="pb-2 pt-4">
                    <div className="flex items-center justify-between gap-4 min-w-0">
                      <CardTitle className="text-sm font-mono flex items-center gap-2 min-w-0 flex-1">
                        <span className="text-muted-foreground font-sans font-normal text-xs shrink-0">
                          Workflow:
                        </span>
                        <Link
                          to="/fixes/$fixId"
                          params={{ fixId: fix.id }}
                          search={{ repoId }}
                          className="truncate hover:underline min-w-0 flex-1"
                        >
                          {workflowLabel(fix.workflow_file_path ?? "")}
                        </Link>
                        <span
                          className={`shrink-0 text-xs font-medium px-2 py-0.5 rounded-full capitalize font-sans ${fixStatusColor(fix.status)}`}
                        >
                          {fix.status}
                        </span>
                      </CardTitle>
                      <div className="flex items-center gap-2 shrink-0">
                        {fix.pr_state === "closed" && fix.pr_id && (
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-7 text-xs gap-1.5"
                            onClick={() =>
                              regenerateMutation.mutate(fix.pr_id!)
                            }
                            disabled={isRegenerating}
                          >
                            <RefreshCw className="h-3 w-3" />
                            {isRegenerating ? "Queuing…" : "Regenerate fix"}
                          </Button>
                        )}
                        {fix.status === "ready" && (
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-7 text-xs gap-1.5"
                            onClick={() =>
                              deliverWorkflowMutation.mutate(fix.id)
                            }
                            disabled={isWfDelivering}
                          >
                            <GitPullRequest className="h-3 w-3" />
                            {isWfDelivering ? "Queuing…" : "Create PR"}
                          </Button>
                        )}
                      </div>
                    </div>
                  </CardHeader>
                  <CardContent className="p-0">
                    <div className="divide-y">
                      {issues.length === 0 ? (
                        <p className="px-6 py-4 text-sm text-muted-foreground">
                          No issue details available.
                        </p>
                      ) : (
                        issues.map((issue) => (
                          <div
                            key={issue.id}
                            className="flex items-start gap-3 px-6 py-3"
                          >
                            {issue.category && (
                              <CategoryIcon
                                category={issue.category}
                                className="mt-0.5 shrink-0 text-base"
                              />
                            )}
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2 flex-wrap">
                                {issue.severity && (
                                  <SeverityChip severity={issue.severity} />
                                )}
                                {issue.rule_slug && (
                                  <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-mono bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300">
                                    {issue.rule_slug}
                                  </span>
                                )}
                                <span className="text-sm break-words min-w-0">
                                  {issue.message}
                                </span>
                              </div>
                              {issue.line_start != null && (
                                <p className="text-xs text-muted-foreground mt-0.5">
                                  Line {issue.line_start}
                                  {issue.line_end &&
                                  issue.line_end !== issue.line_start
                                    ? `–${issue.line_end}`
                                    : ""}
                                </p>
                              )}
                            </div>
                          </div>
                        ))
                      )}
                    </div>
                    <div className="flex items-center justify-between gap-3 px-6 py-3 border-t">
                      <p className="text-xs text-muted-foreground truncate min-w-0">
                        {fix.llm_model}
                      </p>
                      <div className="flex items-center gap-3 shrink-0">
                        {fix.pr_url && (
                          <a
                            href={fix.pr_url}
                            target="_blank"
                            rel="noreferrer"
                            className="text-xs text-blue-600 dark:text-blue-400 hover:underline flex items-center gap-1"
                          >
                            <GitPullRequest className="h-3 w-3" />
                            View PR
                            {fix.pr_state === "closed" && (
                              <span className="text-orange-500 dark:text-orange-400">
                                (closed)
                              </span>
                            )}
                            {fix.pr_state === "merged" && (
                              <span className="text-purple-500 dark:text-purple-400">
                                (merged)
                              </span>
                            )}
                          </a>
                        )}
                        <span className="text-xs text-muted-foreground tabular-nums whitespace-nowrap">
                          {fix.created_at
                            ? new Date(fix.created_at).toLocaleDateString(
                                undefined,
                                {
                                  month: "short",
                                  day: "numeric",
                                },
                              )
                            : "—"}
                        </span>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              )
            })}
            {(fixes?.length ?? 0) > PAGE_SIZE && (
              <div className="flex items-center justify-between py-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={fixesPage === 0}
                  onClick={() => setFixesPage((p) => p - 1)}
                >
                  Previous
                </Button>
                <span className="text-xs text-muted-foreground">
                  Page {fixesPage + 1} of{" "}
                  {Math.ceil((fixes?.length ?? 0) / PAGE_SIZE)}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={(fixesPage + 1) * PAGE_SIZE >= (fixes?.length ?? 0)}
                  onClick={() => setFixesPage((p) => p + 1)}
                >
                  Next
                </Button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
