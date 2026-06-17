import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { ArrowLeft, GitBranch, GitPullRequest, Play, Zap } from "lucide-react"
import { useMemo, useState } from "react"
import { toast } from "sonner"
import type { FixStatus } from "@/client"
import {
  AnalysesService,
  FixesService,
  IssuesService,
  RepositoriesService,
} from "@/client"
import { CategoryIcon } from "@/components/CategoryIcon"
import { GenerateFixButton } from "@/components/GenerateFixButton"
import { GradeBadge } from "@/components/GradeBadge"
import { SeverityChip } from "@/components/SeverityChip"
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

type RepoDetailSearch = { branch?: string }

export const Route = createFileRoute("/_layout/repositories/$repoId")({
  component: RepositoryDetail,
  validateSearch: (search: Record<string, unknown>): RepoDetailSearch => ({
    branch: typeof search.branch === "string" ? search.branch : undefined,
  }),
  head: () => ({
    meta: [{ title: "Repository - GreenSecOps" }],
  }),
})

function statusColor(status: string) {
  switch (status) {
    case "completed":
      return "bg-green-500/15 text-green-700 dark:text-green-400"
    case "running":
      return "bg-blue-500/15 text-blue-700 dark:text-blue-400"
    case "failed":
      return "bg-red-500/15 text-red-700 dark:text-red-400"
    case "pending":
      return "bg-yellow-500/15 text-yellow-700 dark:text-yellow-400"
    default:
      return "bg-muted text-muted-foreground"
  }
}

function fixStatusColor(status: FixStatus): string {
  switch (status) {
    case "delivered":
      return "bg-green-500/15 text-green-700 dark:text-green-400"
    case "ready":
      return "bg-blue-500/15 text-blue-700 dark:text-blue-400"
    case "failed":
      return "bg-red-500/15 text-red-700 dark:text-red-400"
    case "rejected":
      return "bg-muted text-muted-foreground line-through"
    default:
      return "bg-yellow-500/15 text-yellow-700 dark:text-yellow-400"
  }
}

function RepositoryDetail() {
  const { repoId } = Route.useParams()
  const { branch } = Route.useSearch()
  const navigate = Route.useNavigate()
  const queryClient = useQueryClient()
  const [unfixed, setUnfixed] = useState(false)

  const { data: repo, isLoading: repoLoading } = useQuery({
    queryKey: ["repository", repoId],
    queryFn: () => RepositoriesService.getRepository({ repoId }),
  })

  const { data: latestAnalyses } = useQuery({
    queryKey: ["analyses", repoId, "latest"],
    queryFn: () =>
      AnalysesService.listAnalyses({ repoId, limit: 1, status: "completed" }),
  })
  const currentGrade = latestAnalyses?.[0]?.grade ?? null

  const { data: analyses, isLoading: analysesLoading } = useQuery({
    queryKey: ["analyses", repoId, branch],
    queryFn: () =>
      AnalysesService.listAnalyses({
        repoId,
        branch: branch || undefined,
        limit: 100,
      }),
  })

  const { data: issues, isLoading: issuesLoading } = useQuery({
    queryKey: ["issues", "repo", repoId, { unfixed }],
    queryFn: () =>
      IssuesService.listIssues({
        repoId,
        unfixed: unfixed || undefined,
        limit: 200,
      }),
  })

  const { data: fixes, isLoading: fixesLoading } = useQuery({
    queryKey: ["fixes", "repo", repoId],
    queryFn: () => FixesService.listFixes({ repoId, limit: 100 }),
  })

  const triggerMutation = useMutation({
    mutationFn: () => AnalysesService.triggerAnalysis({ repoId }),
    onSuccess: () => {
      toast.success("Analysis queued")
      queryClient.invalidateQueries({ queryKey: ["analyses", repoId] })
    },
    onError: () => toast.error("Failed to trigger analysis"),
  })

  const batchFixMutation = useMutation({
    mutationFn: () => FixesService.triggerFixGenerationForRepo({ repoId }),
    onSuccess: (data) => {
      toast.success(`Queued ${data.queued} fix${data.queued !== 1 ? "es" : ""}`)
      queryClient.invalidateQueries({ queryKey: ["issues", "repo", repoId] })
      queryClient.invalidateQueries({ queryKey: ["fixes", "repo", repoId] })
    },
    onError: () => toast.error("Failed to queue fixes"),
  })

  const branches = analyses
    ? [...new Set(analyses.map((a) => a.branch).filter(Boolean) as string[])]
    : []

  const prBranches = useMemo(() => {
    if (!analyses || !repo) return []
    const nonDefault = analyses.filter(
      (a) => a.branch && a.branch !== repo.default_branch,
    )
    const byBranch = new Map<string, (typeof nonDefault)[0]>()
    for (const a of nonDefault) {
      const existing = byBranch.get(a.branch!)
      if (
        !existing ||
        new Date(a.created_at!).getTime() >
          new Date(existing.created_at!).getTime()
      ) {
        byBranch.set(a.branch!, a)
      }
    }
    return [...byBranch.values()].sort(
      (a, b) =>
        new Date(b.created_at!).getTime() - new Date(a.created_at!).getTime(),
    )
  }, [analyses, repo])

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link
            to="/repositories"
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <div>
            <div className="flex items-center gap-3">
              {repoLoading ? (
                <Skeleton className="h-7 w-64" />
              ) : (
                <h1 className="text-2xl font-bold tracking-tight font-mono">
                  {repo?.full_name}
                </h1>
              )}
              <GradeBadge grade={currentGrade} />
            </div>
            {repo && (
              <span className="inline-flex items-center gap-1 text-xs text-muted-foreground mt-0.5">
                <GitBranch className="h-3 w-3" />
                default: {repo.default_branch}
              </span>
            )}
          </div>
        </div>
        <Button
          variant="outline"
          size="sm"
          className="gap-2"
          onClick={() => triggerMutation.mutate()}
          disabled={triggerMutation.isPending}
        >
          <Play className="h-4 w-4" />
          Run analysis
        </Button>
      </div>

      <Tabs defaultValue="analyses">
        <TabsList>
          <TabsTrigger value="analyses">Analyses</TabsTrigger>
          <TabsTrigger value="issues">
            Issues
            {issues?.length ? (
              <span className="ml-1.5 text-xs bg-muted px-1.5 py-0.5 rounded-full">
                {issues.length}
              </span>
            ) : null}
          </TabsTrigger>
          <TabsTrigger value="fixes">
            Fixes
            {fixes?.length ? (
              <span className="ml-1.5 text-xs bg-muted px-1.5 py-0.5 rounded-full">
                {fixes.length}
              </span>
            ) : null}
          </TabsTrigger>
          <TabsTrigger value="pull-requests">
            <GitPullRequest className="h-3.5 w-3.5 mr-1" />
            Pull Requests
            {prBranches.length > 0 ? (
              <span className="ml-1.5 text-xs bg-muted px-1.5 py-0.5 rounded-full">
                {prBranches.length}
              </span>
            ) : null}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="analyses" className="flex flex-col gap-4 mt-4">
          <div className="flex items-center gap-3">
            <p className="text-sm text-muted-foreground">Branch:</p>
            <Select
              value={branch ?? ""}
              onValueChange={(val) =>
                navigate({ search: val ? { branch: val } : {} })
              }
            >
              <SelectTrigger className="w-48 h-8 text-xs">
                <SelectValue placeholder="All branches" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="">All branches</SelectItem>
                {branches.map((b) => (
                  <SelectItem key={b} value={b}>
                    {b}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {branch && (
              <Button
                variant="ghost"
                size="sm"
                className="h-8 text-xs"
                onClick={() => navigate({ search: {} })}
              >
                Clear
              </Button>
            )}
          </div>

          <Card>
            <CardContent className="p-0">
              {analysesLoading ? (
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
                  <div className="grid grid-cols-[1fr_12rem_10rem_7rem_5rem_9rem] items-center px-6 py-2 border-b text-xs font-medium text-muted-foreground uppercase tracking-wide gap-4">
                    <span>Branch</span>
                    <span>Workflow</span>
                    <span>Triggered by</span>
                    <span className="text-center">Status</span>
                    <span className="text-center">Grade</span>
                    <span className="text-right">Date</span>
                  </div>
                  <div className="divide-y">
                    {analyses.map((a) => (
                      <Link
                        key={a.id}
                        to="/analyses/$analysisId"
                        params={{ analysisId: a.id }}
                        className="grid grid-cols-[1fr_12rem_10rem_7rem_5rem_9rem] items-center px-6 py-3 gap-4 hover:bg-muted/40 transition-colors"
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
                        <span
                          className={`text-xs font-medium px-2 py-0.5 rounded-full capitalize text-center ${statusColor(a.status)}`}
                        >
                          {a.status}
                        </span>
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
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="issues" className="flex flex-col gap-4 mt-4">
          <div className="flex items-center gap-3 flex-wrap">
            <Button
              variant={unfixed ? "default" : "outline"}
              size="sm"
              onClick={() => setUnfixed((v) => !v)}
            >
              Open only
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="gap-2"
              onClick={() => batchFixMutation.mutate()}
              disabled={
                batchFixMutation.isPending || batchFixMutation.isSuccess
              }
            >
              <Zap className="h-4 w-4" />
              {batchFixMutation.isPending
                ? "Queuing…"
                : batchFixMutation.isSuccess
                  ? "Queued"
                  : "Fix all open issues"}
            </Button>
          </div>
          <Card>
            <CardContent className="p-0">
              {issuesLoading ? (
                <div className="flex flex-col gap-2 p-6">
                  {[...Array(5)].map((_, i) => (
                    <Skeleton key={i} className="h-14 w-full" />
                  ))}
                </div>
              ) : !issues?.length ? (
                <p className="text-sm text-muted-foreground p-6 text-center">
                  No issues found.
                </p>
              ) : (
                <div className="divide-y">
                  {issues.map((issue) => (
                    <div
                      key={issue.id}
                      className="flex items-start gap-3 px-6 py-4"
                    >
                      <CategoryIcon
                        category={issue.category}
                        className="mt-0.5 shrink-0 text-base"
                      />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <SeverityChip severity={issue.severity} />
                          <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-mono bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300">
                            {issue.rule_slug}
                          </span>
                          <span className="text-sm">{issue.message}</span>
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
                      <GenerateFixButton
                        issueId={issue.id}
                        fixStatus={issue.fix_status}
                      />
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="fixes" className="mt-4">
          <Card>
            <CardContent className="p-0">
              {fixesLoading ? (
                <div className="flex flex-col gap-2 p-6">
                  {[...Array(4)].map((_, i) => (
                    <Skeleton key={i} className="h-12 w-full" />
                  ))}
                </div>
              ) : !fixes?.length ? (
                <p className="text-sm text-muted-foreground p-6 text-center">
                  No fixes yet.
                </p>
              ) : (
                <>
                  <div className="grid grid-cols-[7rem_1fr_10rem_7rem_8rem] items-center px-6 py-2 border-b text-xs font-medium text-muted-foreground uppercase tracking-wide gap-4">
                    <span>Status</span>
                    <span>Issue</span>
                    <span>Model</span>
                    <span className="text-center">PR / Comment</span>
                    <span className="text-right">Date</span>
                  </div>
                  <div className="divide-y">
                    {fixes.map((fix) => (
                      <div
                        key={fix.id}
                        className="grid grid-cols-[7rem_1fr_10rem_7rem_8rem] items-center px-6 py-3 gap-4"
                      >
                        <span
                          className={`text-xs font-medium px-2 py-0.5 rounded-full capitalize ${fixStatusColor(fix.status)}`}
                        >
                          {fix.status}
                        </span>
                        <span className="text-xs font-mono text-muted-foreground truncate">
                          {fix.issue_id.slice(0, 8)}…
                        </span>
                        <span className="text-xs text-muted-foreground">
                          {fix.llm_model}
                        </span>
                        <div className="flex justify-center text-xs">
                          {fix.pr_url ? (
                            <a
                              href={fix.pr_url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-blue-600 dark:text-blue-400 hover:underline"
                            >
                              PR
                            </a>
                          ) : fix.comment_url ? (
                            <a
                              href={fix.comment_url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-blue-600 dark:text-blue-400 hover:underline"
                            >
                              Comment
                            </a>
                          ) : (
                            "—"
                          )}
                        </div>
                        <span className="text-xs text-muted-foreground tabular-nums whitespace-nowrap text-right">
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
                    ))}
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="pull-requests" className="flex flex-col gap-4 mt-4">
          <Card>
            <CardContent className="p-0">
              {analysesLoading ? (
                <div className="flex flex-col gap-2 p-6">
                  {[...Array(4)].map((_, i) => (
                    <Skeleton key={i} className="h-12 w-full" />
                  ))}
                </div>
              ) : prBranches.length === 0 ? (
                <p className="text-sm text-muted-foreground p-6 text-center">
                  No non-default branch analyses found. Run an analysis on a
                  feature branch to see PR status here.
                </p>
              ) : (
                <>
                  <div className="grid grid-cols-[1fr_12rem_7rem_5rem_9rem] items-center px-6 py-2 border-b text-xs font-medium text-muted-foreground uppercase tracking-wide gap-4">
                    <span>Branch</span>
                    <span>Workflow</span>
                    <span className="text-center">Status</span>
                    <span className="text-center">Grade</span>
                    <span className="text-right">Date</span>
                  </div>
                  <div className="divide-y">
                    {prBranches.map((a) => (
                      <Link
                        key={a.id}
                        to="/analyses/$analysisId"
                        params={{ analysisId: a.id }}
                        className="grid grid-cols-[1fr_12rem_7rem_5rem_9rem] items-center px-6 py-3 gap-4 hover:bg-muted/40 transition-colors"
                      >
                        <span className="text-xs font-mono truncate flex items-center gap-1.5">
                          <GitPullRequest className="h-3 w-3 text-muted-foreground shrink-0" />
                          {a.branch}
                        </span>
                        <span className="text-xs font-mono text-muted-foreground truncate">
                          {a.workflow_file_path
                            ? a.workflow_file_path.split("/").pop()
                            : "—"}
                        </span>
                        <span
                          className={`text-xs font-medium px-2 py-0.5 rounded-full capitalize text-center ${statusColor(a.status)}`}
                        >
                          {a.status}
                        </span>
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
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}
