import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { ArrowLeft, GitBranch } from "lucide-react"
import { AnalysesService, RepositoriesService } from "@/client"
import { GradeBadge } from "@/components/GradeBadge"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

export const Route = createFileRoute("/_layout/repositories_/$repoId")({
  component: RepositoryDetail,
  head: () => ({
    meta: [{ title: "Repository - GreenSecOps" }],
  }),
})

function RepositoryDetail() {
  const { repoId } = Route.useParams()

  const { data: repo, isLoading: repoLoading } = useQuery({
    queryKey: ["repository", repoId],
    queryFn: () => RepositoriesService.getRepository({ repoId }),
  })

  const { data: analyses, isLoading: analysesLoading } = useQuery({
    queryKey: ["analyses", repoId],
    queryFn: () => AnalysesService.listAnalyses({ repoId, limit: 100 }),
    enabled: !!repoId,
  })

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-3">
        <Link
          to="/repositories"
          className="text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
        </Link>
        <div>
          {repoLoading ? (
            <Skeleton className="h-7 w-48" />
          ) : (
            <>
              <h1 className="text-2xl font-bold tracking-tight">
                {repo?.full_name ?? repoId}
              </h1>
              {repo && (
                <span className="inline-flex items-center gap-1 text-xs font-mono text-muted-foreground mt-0.5">
                  <GitBranch className="h-3 w-3" />
                  {repo.default_branch}
                </span>
              )}
            </>
          )}
        </div>
      </div>

      <div className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">Analyses</h2>
        {analysesLoading ? (
          <div className="flex flex-col gap-2">
            {[...Array(5)].map((_, i) => (
              <Skeleton key={i} className="h-14 w-full" />
            ))}
          </div>
        ) : !analyses?.length ? (
          <Card>
            <CardContent className="py-8 text-center text-muted-foreground text-sm">
              No analyses found for this repository.
            </CardContent>
          </Card>
        ) : (
          <Card>
            <CardContent className="p-0">
              <div className="grid grid-cols-[2fr_1fr_1fr_1fr] items-center px-6 py-2 border-b text-xs font-medium text-muted-foreground uppercase tracking-wide">
                <span>Workflow file</span>
                <span>Branch</span>
                <span>Grade</span>
                <span>Status</span>
              </div>
              <div className="divide-y">
                {analyses.map((analysis) => (
                  <Link
                    key={analysis.id}
                    to="/analyses/$analysisId"
                    params={{ analysisId: analysis.id }}
                    className="grid grid-cols-[2fr_1fr_1fr_1fr] items-center px-6 py-3 gap-4 hover:bg-muted/50 transition-colors"
                  >
                    <span className="text-sm font-mono truncate">
                      {analysis.workflow_file_id}
                    </span>
                    <span className="text-sm font-mono text-muted-foreground">
                      {analysis.branch ?? "—"}
                    </span>
                    <GradeBadge grade={analysis.grade ?? null} />
                    <span className="text-sm capitalize text-muted-foreground">
                      {analysis.status}
                    </span>
                  </Link>
                ))}
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}
