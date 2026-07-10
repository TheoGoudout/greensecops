import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { useMemo, useState } from "react"
import { AnalysesService } from "@/client"
import { GradeBadge } from "@/components/GradeBadge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { analysisStatusColor, analysisStatusLabel } from "@/lib/status-colors"
import { PAGE_SIZE } from "@/lib/workflow-utils"
import { Route as RepoRoute } from "@/routes/_layout/repositories/$repoId"

export const Route = createFileRoute("/_layout/repositories/$repoId/analyses")({
  component: AnalysesPage,
  head: () => ({
    meta: [{ title: "Analyses - GreenSecOps" }],
  }),
})

function AnalysesPage() {
  const { repoId } = Route.useParams()
  const { branch } = RepoRoute.useSearch()
  const [page, setPage] = useState(0)

  const { data: analyses, isLoading } = useQuery({
    queryKey: ["analyses", repoId, branch],
    queryFn: () =>
      AnalysesService.listAnalyses({
        repoId,
        branch: branch || undefined,
        limit: 100,
      }),
  })

  const paged = useMemo(
    () => (analyses ?? []).slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE),
    [analyses, page],
  )

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="flex flex-col gap-2 p-6">
              {[...Array(4)].map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : !analyses?.length ? (
            <p className="text-sm text-muted-foreground p-6 text-center">
              No analyses found{branch ? ` for branch "${branch}"` : ""}.
            </p>
          ) : (
            <>
              <div className="overflow-x-auto">
                <div className="grid grid-cols-[1fr_12rem_10rem_7rem_5rem_9rem] min-w-[44rem] items-center px-6 py-2 border-b text-xs font-medium text-muted-foreground uppercase tracking-wide gap-4">
                  <span>Branch</span>
                  <span>Workflow</span>
                  <span>Triggered by</span>
                  <span className="text-center">Status</span>
                  <span className="text-center">Grade</span>
                  <span className="text-right">Date</span>
                </div>
                <div className="divide-y">
                  {paged.map((a) => (
                    <Link
                      key={a.id}
                      to="/analyses/$analysisId"
                      params={{ analysisId: a.id }}
                      className="grid grid-cols-[1fr_12rem_10rem_7rem_5rem_9rem] min-w-[44rem] items-center px-6 py-3 gap-4 hover:bg-muted/40 transition-colors"
                    >
                      <span className="text-xs font-mono truncate">
                        {a.branch ?? "—"}
                      </span>
                      <span className="text-xs font-mono text-muted-foreground truncate">
                        {a.workflow_file_path
                          ? a.workflow_file_path.split("/").pop()
                          : "—"}
                      </span>
                      <span className="text-xs text-muted-foreground capitalize">
                        {a.triggered_by.replace(/_/g, " ")}
                      </span>
                      <div className="flex justify-center">
                        <span
                          className={`text-xs font-medium px-2 py-0.5 rounded-full ${analysisStatusColor(a.status)}`}
                        >
                          {analysisStatusLabel(a.status)}
                        </span>
                      </div>
                      <div className="flex justify-center">
                        <GradeBadge grade={a.grade ?? null} />
                      </div>
                      <span className="text-xs text-muted-foreground tabular-nums whitespace-nowrap text-right">
                        {a.created_at
                          ? new Date(a.created_at).toLocaleDateString(
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
                    </Link>
                  ))}
                </div>
              </div>
              {(analyses?.length ?? 0) > PAGE_SIZE && (
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
                    Page {page + 1} of{" "}
                    {Math.ceil((analyses?.length ?? 0) / PAGE_SIZE)}
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={(page + 1) * PAGE_SIZE >= (analyses?.length ?? 0)}
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
