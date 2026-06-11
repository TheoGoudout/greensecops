import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import type { LucideIcon } from "lucide-react"
import { Activity, GitBranch, ShieldCheck, TrendingUp } from "lucide-react"

import { GradeBadge } from "@/components/GradeBadge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import useAuth from "@/hooks/useAuth"
import { listAnalyses, listRepositories } from "@/lib/api/services"

export const Route = createFileRoute("/_layout/dashboard")({
  component: Dashboard,
  head: () => ({
    meta: [{ title: "Dashboard - GreenSecOps" }],
  }),
})

function StatCard({
  icon: Icon,
  title,
  value,
  loading,
}: {
  icon: LucideIcon
  title: string
  value: string | number
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
          <p className="text-2xl font-bold">{value}</p>
        )}
      </CardContent>
    </Card>
  )
}

function Dashboard() {
  const { user } = useAuth()

  const { data: repos, isLoading: reposLoading } = useQuery({
    queryKey: ["repositories"],
    queryFn: () => listRepositories({ limit: 200 }),
  })

  const { data: analyses, isLoading: analysesLoading } = useQuery({
    queryKey: ["analyses", "recent"],
    queryFn: () => listAnalyses({ limit: 20 }),
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

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">
          Welcome back, {user?.full_name ?? user?.email}
        </h1>
        <p className="text-muted-foreground">
          Here's an overview of your CI/CD health
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          icon={GitBranch}
          title="Total Repositories"
          value={repos?.length ?? 0}
          loading={reposLoading}
        />
        <StatCard
          icon={Activity}
          title="Active Repositories"
          value={activeCount}
          loading={reposLoading}
        />
        <StatCard
          icon={ShieldCheck}
          title="Recent Analyses"
          value={analyses?.length ?? 0}
          loading={analysesLoading}
        />
        <StatCard
          icon={TrendingUp}
          title="Avg Health Score"
          value={avgScore !== null ? `${avgScore}/100` : "—"}
          loading={analysesLoading}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Recent Analyses</CardTitle>
        </CardHeader>
        <CardContent>
          {analysesLoading ? (
            <div className="flex flex-col gap-2">
              {[...Array(5)].map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : !analyses?.length ? (
            <p className="text-sm text-muted-foreground py-4 text-center">
              No analyses yet. Trigger one from the Repositories page.
            </p>
          ) : (
            <div className="divide-y">
              {analyses.map((analysis) => (
                <div
                  key={analysis.id}
                  className="flex items-center justify-between py-3 gap-4"
                >
                  <div className="flex flex-col gap-0.5 min-w-0">
                    <Link
                      to="/analyses/$analysisId"
                      params={{ analysisId: analysis.id }}
                      className="text-sm font-medium hover:underline truncate"
                    >
                      {analysis.commit_sha?.slice(0, 7) ?? "—"}{" "}
                      <span className="text-muted-foreground font-normal">
                        · {analysis.branch ?? "default branch"}
                      </span>
                    </Link>
                    <span className="text-xs text-muted-foreground capitalize">
                      {analysis.status} ·{" "}
                      {analysis.created_at
                        ? new Date(analysis.created_at).toLocaleDateString()
                        : "—"}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    {analysis.score !== null && (
                      <span className="text-sm text-muted-foreground">
                        {Math.round(analysis.score)}/100
                      </span>
                    )}
                    <GradeBadge grade={analysis.grade} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
