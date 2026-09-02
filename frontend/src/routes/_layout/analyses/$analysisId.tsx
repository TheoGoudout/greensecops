import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { AlertCircle, ArrowLeft, ExternalLink } from "lucide-react"
import { toast } from "sonner"
import type { Category, WorkflowFindingPublic } from "@/client"
import { RepositoriesService, WorkflowService } from "@/client"
import { CategoryIcon } from "@/components/CategoryIcon"
import { EngineActionButton } from "@/components/EngineActionBar"
import { GradeBadge } from "@/components/GradeBadge"
import { SeverityChip } from "@/components/SeverityChip"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useOrgQuotas } from "@/hooks/useOrgQuotas"
import { engineActions } from "@/lib/engine-actions"
import { ISSUE_CATEGORIES } from "@/lib/issue-constants"
import { pollWhileScanning } from "@/lib/scan-polling"

export const Route = createFileRoute("/_layout/analyses/$analysisId")({
  component: AnalysisDetail,
  head: () => ({
    meta: [{ title: "Analysis - GreenSecOps" }],
  }),
})

function groupByCategory(
  issues: WorkflowFindingPublic[],
): Record<Category, WorkflowFindingPublic[]> {
  const groups = Object.fromEntries(
    ISSUE_CATEGORIES.map((c) => [c, [] as WorkflowFindingPublic[]]),
  ) as Record<Category, WorkflowFindingPublic[]>
  for (const issue of issues) {
    groups[issue.category].push(issue)
  }
  return groups
}

function AnalysisDetail() {
  const { analysisId } = Route.useParams()
  const queryClient = useQueryClient()

  const {
    data: analysis,
    isLoading: analysisLoading,
    isError: analysisError,
  } = useQuery({
    queryKey: ["scan", analysisId],
    queryFn: () => WorkflowService.getScan({ scanId: analysisId }),
  })

  const { data: issues, isLoading: issuesLoading } = useQuery({
    queryKey: ["findings", analysisId],
    queryFn: () =>
      WorkflowService.listFindings({ scanId: analysisId, limit: 500 }),
    enabled: !!analysisId,
  })

  const { data: repo } = useQuery({
    queryKey: ["repository", analysis?.repo_id],
    queryFn: () =>
      RepositoriesService.getRepository({ repoId: analysis!.repo_id }),
    enabled: !!analysis?.repo_id,
  })
  const isAccessible = repo?.is_accessible ?? true
  const quota = useOrgQuotas(repo?.org_id)

  // The button below acts on the whole repository (the route is
  // `POST /repositories/{id}/fixes`), so it answers to the repository's
  // activity, not this one analysis's — a scan running anywhere in the repo
  // refuses it, and so does a fix already in flight.
  const { data: repoScans } = useQuery({
    queryKey: ["scans", analysis?.repo_id],
    queryFn: () =>
      WorkflowService.listScans({ repoId: analysis!.repo_id, limit: 100 }),
    enabled: !!analysis?.repo_id,
    refetchInterval: (query) =>
      pollWhileScanning((query.state.data ?? []).map((a) => a.status)),
  })
  const { data: repoFixes } = useQuery({
    queryKey: ["fixes", "repo", analysis?.repo_id],
    queryFn: () =>
      WorkflowService.listFixes({ repoId: analysis!.repo_id, limit: 100 }),
    enabled: !!analysis?.repo_id,
  })

  const fixMutation = useMutation({
    mutationFn: () =>
      WorkflowService.generateRepositoryFixes({
        repoId: analysis!.repo_id,
        force: true,
        requestBody: issues?.length
          ? { issue_ids: issues.map((i) => i.id) }
          : undefined,
      }),
    onSuccess: () => {
      toast.success("Fix generation queued")
      queryClient.invalidateQueries({
        queryKey: ["fixes", "repo", analysis?.repo_id],
      })
      queryClient.invalidateQueries({ queryKey: ["quotas"] })
    },
    onError: () => toast.error("Failed to queue fix"),
  })

  const fixAction = engineActions({
    targetLabel: "repository",
    scope: "repo",
    isAccessible,
    enabled: repo?.enabled,
    quota,
    scanStatus: (repoScans ?? []).map((a) => a.status),
    fixStatuses: (repoFixes ?? []).map((f) => f.status),
    openFindingCount: issues?.length ?? 0,
    pending: { generate: fixMutation.isPending },
  }).generate

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
                ? "/workflows/$repoId/static-analysis"
                : "/workflows"
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
          <EngineActionButton
            action={fixAction}
            onClick={() => fixMutation.mutate()}
          />
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
                  {analysis.file_path ?? "—"}
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
                      analysis?.file_path &&
                      issue.line_start != null
                        ? `https://github.com/${analysis.repo_full_name}/blob/${analysis?.branch ?? "main"}/${analysis.file_path}#L${issue.line_start}${issue.line_end && issue.line_end !== issue.line_start ? `-L${issue.line_end}` : ""}`
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
