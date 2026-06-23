import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import type { LucideIcon } from "lucide-react"
import {
  Activity,
  AlertCircle,
  ChevronRight,
  GitBranch,
  TrendingUp,
} from "lucide-react"
import { AnalysesService, IssuesService, RepositoriesService } from "@/client"
import { GradeBadge } from "@/components/GradeBadge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

export const Route = createFileRoute("/_layout/dashboard")({
  component: Dashboard,
  head: () => ({
    meta: [{ title: "Dashboard - GreenSecOps" }],
  }),
})

function relativeTime(dateStr: string | null | undefined): string {
  if (!dateStr) return "—"
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return "just now"
  if (mins < 60) return `${mins} minute${mins !== 1 ? "s" : ""} ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs} hour${hrs !== 1 ? "s" : ""} ago`
  const days = Math.floor(hrs / 24)
  if (days === 1) return "yesterday"
  return new Date(dateStr).toLocaleDateString()
}

function StatCard({
  icon: Icon,
  title,
  value,
  hint,
  loading,
}: {
  icon: LucideIcon
  title: string
  value: string | number
  hint?: string
  loading: boolean
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>
        {loading ? (
          <Skeleton className="h-8 w-16" />
        ) : (
          <>
            <p className="text-2xl font-bold">{value}</p>
            {hint && (
              <p className="text-xs text-muted-foreground mt-0.5">{hint}</p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}

function Dashboard() {
  const { data: repos, isLoading: reposLoading } = useQuery({
    queryKey: ["repositories"],
    queryFn: () => RepositoriesService.listRepositories({ limit: 200 }),
  })

  const { data: analyses, isLoading: analysesLoading } = useQuery({
    queryKey: ["analyses", "recent"],
    queryFn: () => AnalysesService.listAnalyses({ limit: 20 }),
  })

  const { data: issues, isLoading: issuesLoading } = useQuery({
    queryKey: ["issues", "open"],
    queryFn: () => IssuesService.listIssues({ limit: 200 }),
  })

  const activeCount = repos?.filter((r) => r.enabled).length ?? 0
  const completedAnalyses =
    analyses?.filter((a) => a.status === "completed") ?? []
  const scores = completedAnalyses
    .map((a) => a.score)
    .filter((s): s is number => s !== null)
  const avgScore =
    scores.length > 0
      ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length)
      : null

  const criticalCount =
    issues?.filter((i) => i.severity === "critical").length ?? 0

  const repoMap = new Map(repos?.map((r) => [r.id, r]) ?? [])

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
        <p className="text-muted-foreground">
          Overview of your CI/CD health across all connected repositories.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          icon={Activity}
          title="Total analyses"
          value={analyses?.length ?? 0}
          loading={analysesLoading}
        />
        <StatCard
          icon={GitBranch}
          title="Active repositories"
          value={activeCount}
          hint={`of ${repos?.length ?? 0} connected`}
          loading={reposLoading}
        />
        <StatCard
          icon={TrendingUp}
          title="Average score"
          value={avgScore !== null ? `${avgScore}/100` : "—/100"}
          loading={analysesLoading}
        />
        <StatCard
          icon={AlertCircle}
          title="Open issues"
          value={issues?.length ?? 0}
          hint={`${criticalCount} critical`}
          loading={issuesLoading}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Recent Analyses</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {analysesLoading ? (
            <div className="flex flex-col gap-2 p-6">
              {[...Array(5)].map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : !analyses?.length ? (
            <p className="text-sm text-muted-foreground py-4 px-6 text-center">
              No analyses yet. Trigger one from the Repositories page.
            </p>
          ) : (
            <>
              <div className="grid grid-cols-[2fr_1fr_1fr_4rem_5rem_1.5rem] items-center px-6 py-2 border-b text-xs font-medium text-muted-foreground uppercase tracking-wide gap-4">
                <span>Repository</span>
                <span>Commit</span>
                <span>Analyzed</span>
                <span>Grade</span>
                <span>Score</span>
                <span />
              </div>
              <div className="divide-y">
                {analyses.map((analysis) => {
                  const repo = repoMap.get(analysis.repo_id)
                  return (
                    <Link
                      key={analysis.id}
                      to="/analyses/$analysisId"
                      params={{ analysisId: analysis.id }}
                      className="grid grid-cols-[2fr_1fr_1fr_4rem_5rem_1.5rem] items-center px-6 py-3 gap-4 hover:bg-muted/50 transition-colors"
                    >
                      <span className="text-sm font-medium truncate">
                        {repo?.full_name ?? "—"}
                      </span>
                      <span className="font-mono text-xs text-muted-foreground">
                        {analysis.commit_sha?.slice(0, 7) ?? "—"}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {relativeTime(
                          analysis.completed_at ?? analysis.created_at,
                        )}
                      </span>
                      <GradeBadge grade={analysis.grade ?? null} />
                      <span className="text-xs text-muted-foreground">
                        {analysis.score != null
                          ? `${Math.round(analysis.score)}/100`
                          : "—"}
                      </span>
                      <ChevronRight className="h-4 w-4 text-muted-foreground" />
                    </Link>
                  )
                })}
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
