import { useMutation, useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { AlertCircle, ArrowLeft, ExternalLink, Wand2 } from "lucide-react"
import { toast } from "sonner"
import type { Category, IssuePublic } from "@/client"
import {
  RepositoriesService,
  WorkflowFindingsService,
  WorkflowFixesService,
  WorkflowScansService,
} from "@/client"
import { CategoryIcon } from "@/components/CategoryIcon"
import { GradeBadge } from "@/components/GradeBadge"
import { SeverityChip } from "@/components/SeverityChip"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { ISSUE_CATEGORIES } from "@/lib/issue-constants"

export const Route = createFileRoute("/_layout/analyses/$analysisId")({
  component: AnalysisDetail,
  head: () => ({
    meta: [{ title: "Analysis - GreenSecOps" }],
  }),
})

function groupByCategory(
  issues: IssuePublic[],
): Record<Category, IssuePublic[]> {
  const groups = Object.fromEntries(
    ISSUE_CATEGORIES.map((c) => [c, [] as IssuePublic[]]),
  ) as Record<Category, IssuePublic[]>
  for (const issue of issues) {
    groups[issue.category].push(issue)
  }
  return groups
}

function AnalysisDetail() {
  const { analysisId } = Route.useParams()

  const {
    data: analysis,
    isLoading: analysisLoading,
    isError: analysisError,
  } = useQuery({
    queryKey: ["analysis", analysisId],
    queryFn: () => WorkflowScansService.getAnalysis({ analysisId }),
  })

  const { data: issues, isLoading: issuesLoading } = useQuery({
    queryKey: ["issues", analysisId],
    queryFn: () =>
      WorkflowFindingsService.listIssues({ analysisId, limit: 500 }),
    enabled: !!analysisId,
  })

  const { data: repo } = useQuery({
    queryKey: ["repository", analysis?.repo_id],
    queryFn: () =>
      RepositoriesService.getRepository({ repoId: analysis!.repo_id }),
    enabled: !!analysis?.repo_id,
  })
  const isAccessible = repo?.is_accessible ?? true

  const fixMutation = useMutation({
    mutationFn: () =>
      WorkflowFixesService.triggerFixGenerationForRepo({
        repoId: analysis!.repo_id,
        force: true,
        requestBody: issues?.length
          ? { issue_ids: issues.map((i) => i.id) }
          : undefined,
      }),
    onSuccess: () => toast.success("Fix generation queued"),
    onError: () => toast.error("Failed to queue fix"),
  })

  const grouped = issues ? groupByCategory(issues) : null

  if (analysisError) {
    return (
      <Alert variant="destructive">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>
          Analysis not found or failed to load.
        </AlertDescription>
      </Alert>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Link
            to={
              analysis?.repo_id
                ? "/repositories/$repoId/static-analysis"
                : "/repositories"
            }
            params={
              analysis?.repo_id ? { repoId: analysis.repo_id } : undefined
            }
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">
              Analysis Detail
            </h1>
            <p className="text-muted-foreground text-sm font-mono">
              {analysisId}
            </p>
          </div>
        </div>
        {analysis?.repo_id && (
          <Button
            variant="outline"
            size="sm"
            className="gap-2 shrink-0"
            onClick={() => fixMutation.mutate()}
            disabled={!isAccessible || fixMutation.isPending || !issues?.length}
          >
            <Wand2 className="h-4 w-4" />
            {fixMutation.isPending ? "Queuing…" : "Generate fix"}
          </Button>
        )}
      </div>

      {analysisLoading ? (
        <Skeleton className="h-32 w-full" />
      ) : analysis ? (
        <Card>
          <CardContent className="pt-6">
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-5">
              <div>
                <p className="text-xs text-muted-foreground mb-1">Grade</p>
                <GradeBadge
                  grade={analysis.grade ?? null}
                  className="text-sm px-3 py-1"
                />
              </div>
              <div>
                <p className="text-xs text-muted-foreground mb-1">Score</p>
                <p className="text-xl font-bold">
                  {analysis.score != null
                    ? `${Math.round(analysis.score)}/100`
                    : "—"}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground mb-1">Status</p>
                <p className="text-sm font-medium capitalize">
                  {analysis.status}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground mb-1">Branch</p>
                <p className="text-sm font-medium font-mono">
                  {analysis.branch ?? "—"}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground mb-1">
                  Workflow file
                </p>
                <p className="text-xs font-mono text-muted-foreground truncate">
                  {analysis.workflow_file_path ?? "—"}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      ) : null}

      <div className="flex flex-col gap-4">
        <h2 className="text-lg font-semibold">Issues</h2>
        {issuesLoading ? (
          <div className="flex flex-col gap-2">
            {[...Array(3)].map((_, i) => (
              <Skeleton key={i} className="h-24 w-full" />
            ))}
          </div>
        ) : !issues?.length ? (
          <Card>
            <CardContent className="py-8 text-center text-muted-foreground text-sm">
              No issues found for this analysis.
            </CardContent>
          </Card>
        ) : (
          ISSUE_CATEGORIES.filter(
            (cat) => grouped && grouped[cat].length > 0,
          ).map((cat) => (
            <Card key={cat}>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <CategoryIcon category={cat} withLabel />
                  <span className="text-muted-foreground font-normal">
                    ({grouped![cat].length})
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <div className="divide-y">
                  {grouped![cat].map((issue) => {
                    const githubUrl =
                      analysis?.repo_full_name &&
                      analysis?.workflow_file_path &&
                      issue.line_start != null
                        ? `https://github.com/${analysis.repo_full_name}/blob/${analysis?.branch ?? "main"}/${analysis.workflow_file_path}#L${issue.line_start}${issue.line_end && issue.line_end !== issue.line_start ? `-L${issue.line_end}` : ""}`
                        : null

                    return (
                      <div
                        key={issue.id}
                        className="px-6 py-3 flex items-start gap-3"
                      >
                        <SeverityChip
                          severity={issue.severity}
                          className="mt-0.5 shrink-0"
                        />
                        <div className="flex-1 min-w-0">
                          <p className="text-sm">{issue.message}</p>
                          {issue.line_start !== null && (
                            <div className="mt-0.5">
                              {githubUrl ? (
                                <a
                                  href={githubUrl}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
                                >
                                  Line {issue.line_start}
                                  {issue.line_end &&
                                  issue.line_end !== issue.line_start
                                    ? `–${issue.line_end}`
                                    : ""}
                                  <ExternalLink className="h-3 w-3" />
                                </a>
                              ) : (
                                <p className="text-xs text-muted-foreground">
                                  Line {issue.line_start}
                                  {issue.line_end &&
                                  issue.line_end !== issue.line_start
                                    ? `–${issue.line_end}`
                                    : ""}
                                </p>
                              )}
                            </div>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </CardContent>
            </Card>
          ))
        )}
      </div>
    </div>
  )
}
