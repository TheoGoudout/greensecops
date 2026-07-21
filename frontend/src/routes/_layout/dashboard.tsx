import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import type { LucideIcon } from "lucide-react"
import {
  Activity,
  AlertCircle,
  CheckCircle2,
  CreditCard,
  GitBranch,
  TrendingDown,
  TrendingUp,
} from "lucide-react"
import { useMemo } from "react"
import {
  AnalysesService,
  BillingService,
  IssuesService,
  RepositoriesService,
} from "@/client"
import { GradeBadge } from "@/components/GradeBadge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

export const Route = createFileRoute("/_layout/dashboard")({
  component: Dashboard,
  head: () => ({
    meta: [{ title: "Dashboard - GreenSecOps" }],
  }),
})

const GRADE_ORDER = ["A+++", "A++", "A+", "A", "B", "C", "D", "E", "F"]

const TIER_LABELS: Record<string, string> = {
  free: "Free",
  starter: "Starter",
  pro: "Pro",
  ultimate: "Ultimate",
  open_source: "Open Source",
}

type TierLimits = {
  tier: string
  limits: Record<string, number | null>
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

function UsageBar({
  label,
  used,
  limit,
}: {
  label: string
  used: number
  limit: number | null
}) {
  const pct =
    limit != null ? Math.min(Math.round((used / limit) * 100), 100) : null
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-medium tabular-nums">
          {limit != null ? `${used} / ${limit}` : `${used} / ∞`}
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-muted overflow-hidden">
        <div
          className={cn(
            "h-full rounded-full transition-all",
            pct != null && pct >= 90
              ? "bg-red-500"
              : pct != null && pct >= 70
                ? "bg-amber-500"
                : "bg-primary",
          )}
          style={{ width: pct != null ? `${pct}%` : "4px" }}
        />
      </div>
    </div>
  )
}

function ScoreDelta({ value }: { value: number }) {
  if (Math.abs(value) < 0.5) {
    return <span className="text-xs text-muted-foreground">—</span>
  }
  const sign = value > 0 ? "+" : ""
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 text-xs font-medium",
        value > 0
          ? "text-emerald-600 dark:text-emerald-400"
          : "text-red-600 dark:text-red-400",
      )}
    >
      {value > 0 ? (
        <TrendingUp className="h-3 w-3" />
      ) : (
        <TrendingDown className="h-3 w-3" />
      )}
      {sign}
      {Math.round(value)}
    </span>
  )
}

function Dashboard() {
  const { data: repos, isLoading: reposLoading } = useQuery({
    queryKey: ["repositories"],
    queryFn: () => RepositoriesService.listRepositories({ limit: 200 }),
  })

  const { data: analyses, isLoading: analysesLoading } = useQuery({
    queryKey: ["analyses", "recent"],
    queryFn: () => AnalysesService.listAnalyses({ limit: 200 }),
  })

  const { data: openIssues, isLoading: openIssuesLoading } = useQuery({
    queryKey: ["issues", "open"],
    queryFn: () => IssuesService.listIssues({ limit: 200 }),
  })

  const { data: allIssues, isLoading: allIssuesLoading } = useQuery({
    queryKey: ["issues", "all"],
    queryFn: () =>
      IssuesService.listIssues({ includeResolved: true, limit: 200 }),
  })

  const { data: subscription, isLoading: subscriptionLoading } = useQuery({
    queryKey: ["billing", "subscription"],
    queryFn: () => BillingService.getSubscription(),
  })

  const { data: tierLimitsRaw, isLoading: tierLimitsLoading } = useQuery({
    queryKey: ["billing", "limits"],
    queryFn: () => BillingService.getTierLimits(),
  })

  const tierLimits = tierLimitsRaw as unknown as TierLimits | undefined

  // Stat card computations
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

  const openCount = openIssues?.length ?? 0
  const totalIssueCount = allIssues?.length ?? 0
  const resolvedCount = Math.max(totalIssueCount - openCount, 0)
  const criticalCount =
    openIssues?.filter((i) => i.severity === "critical").length ?? 0

  const fixRate =
    totalIssueCount > 0
      ? Math.round((resolvedCount / totalIssueCount) * 100)
      : 0

  // Per-repo first vs. latest score averaged across all workflow files
  const repoHealthData = useMemo(() => {
    if (!analyses || !repos) return []
    const repoMap = new Map(repos.map((r) => [r.id, r]))

    const completed = analyses.filter(
      (a) =>
        a.status === "completed" &&
        a.score != null &&
        a.workflow_file_id != null,
    )

    // Group by repo → workflow file; analyses arrive newest-first
    const byRepoWf = new Map<string, Map<string, typeof completed>>()
    for (const a of completed) {
      if (!byRepoWf.has(a.repo_id)) byRepoWf.set(a.repo_id, new Map())
      const wfMap = byRepoWf.get(a.repo_id)!
      const bucket = wfMap.get(a.workflow_file_id!) ?? []
      bucket.push(a)
      wfMap.set(a.workflow_file_id!, bucket)
    }

    const avg = (arr: number[]) => arr.reduce((a, b) => a + b, 0) / arr.length

    return Array.from(byRepoWf.entries())
      .map(([repoId, wfMap]) => {
        const repo = repoMap.get(repoId)
        if (!repo) return null
        const buckets = Array.from(wfMap.values())
        const latestScore = avg(buckets.map((b) => b[0].score!))
        const firstScore = avg(buckets.map((b) => b[b.length - 1].score!))
        return {
          repoId,
          repo,
          firstScore,
          latestScore,
          latestGrade: repo.grade ?? null,
          delta: latestScore - firstScore,
        }
      })
      .filter((d): d is NonNullable<typeof d> => d != null)
      .sort((a, b) => b.delta - a.delta)
  }, [analyses, repos])

  // Grade distribution across repos
  const gradeDistribution = useMemo(() => {
    if (!repos) return []
    const counts = new Map<string, number>()
    for (const repo of repos) {
      if (repo.grade) {
        counts.set(repo.grade, (counts.get(repo.grade) ?? 0) + 1)
      }
    }
    return GRADE_ORDER.map((grade) => ({
      grade,
      count: counts.get(grade) ?? 0,
    })).filter(({ count }) => count > 0)
  }, [repos])

  const maxGradeCount = Math.max(...gradeDistribution.map((g) => g.count), 1)
  const billingLoading = subscriptionLoading || tierLimitsLoading
  const limits = tierLimits?.limits

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
        <p className="text-muted-foreground">
          Security posture and progress across all connected repositories.
        </p>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          icon={Activity}
          title="Total analyses"
          value={completedAnalyses.length}
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
          value={openCount}
          hint={`${resolvedCount} resolved · ${criticalCount} critical`}
          loading={openIssuesLoading || allIssuesLoading}
        />
      </div>

      {/* Repo Health + Billing */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="text-base">Repository Health</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {analysesLoading || reposLoading ? (
              <div className="flex flex-col gap-2 p-6">
                {[...Array(4)].map((_, i) => (
                  <Skeleton key={i} className="h-10 w-full" />
                ))}
              </div>
            ) : repoHealthData.length === 0 ? (
              <p className="text-sm text-muted-foreground py-8 px-6 text-center">
                No completed analyses yet.
              </p>
            ) : (
              <>
                <div className="grid grid-cols-[1fr_3.5rem_4rem_4rem_4rem] items-center px-6 py-2 border-b text-xs font-medium text-muted-foreground uppercase tracking-wide gap-3">
                  <span>Repository</span>
                  <span>Grade</span>
                  <span className="text-right">First</span>
                  <span className="text-right">Latest</span>
                  <span className="text-right">Delta</span>
                </div>
                <div className="divide-y">
                  {repoHealthData.map(
                    ({
                      repoId,
                      repo,
                      firstScore,
                      latestScore,
                      latestGrade,
                      delta,
                    }) => (
                      <Link
                        key={repoId}
                        to="/repositories/$repoId/static-analysis"
                        params={{ repoId }}
                        className="grid grid-cols-[1fr_3.5rem_4rem_4rem_4rem] items-center px-6 py-3 gap-3 hover:bg-muted/50 transition-colors"
                      >
                        <span className="text-sm font-medium truncate">
                          {repo!.full_name}
                        </span>
                        <GradeBadge grade={latestGrade} />
                        <span className="text-xs text-muted-foreground text-right tabular-nums">
                          {Math.round(firstScore)}
                        </span>
                        <span className="text-xs font-medium text-right tabular-nums">
                          {Math.round(latestScore)}
                        </span>
                        <div className="flex justify-end">
                          <ScoreDelta value={delta} />
                        </div>
                      </Link>
                    ),
                  )}
                </div>
              </>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center justify-between">
              <span className="flex items-center gap-2">
                <CreditCard className="h-4 w-4 text-muted-foreground" />
                Plan Usage
              </span>
              {subscription && (
                <span className="text-xs font-normal bg-primary/10 text-primary px-2 py-0.5 rounded-full">
                  {TIER_LABELS[subscription.tier] ?? subscription.tier}
                </span>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {billingLoading ? (
              <div className="space-y-4">
                {[...Array(3)].map((_, i) => (
                  <Skeleton key={i} className="h-8 w-full" />
                ))}
              </div>
            ) : subscription ? (
              <>
                <UsageBar
                  label="Analyses"
                  used={subscription.analyses_used}
                  limit={limits?.analyses ?? null}
                />
                <UsageBar
                  label="Fixes"
                  used={subscription.fixes_used}
                  limit={limits?.fixes ?? null}
                />
                <UsageBar
                  label="Repositories"
                  used={subscription.repos_used ?? 0}
                  limit={limits?.repos ?? null}
                />
                {subscription.period_end && (
                  <p className="text-xs text-muted-foreground text-right">
                    Analyses/fixes reset{" "}
                    {new Date(subscription.period_end).toLocaleDateString(
                      undefined,
                      { year: "numeric", month: "short", day: "numeric" },
                    )}
                  </p>
                )}
              </>
            ) : (
              <p className="text-sm text-muted-foreground text-center py-4">
                No billing data available.
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Fix Rate + Grade Distribution */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-muted-foreground" />
              Fix Rate
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col items-center justify-center gap-3 pt-4 pb-6">
            {openIssuesLoading || allIssuesLoading ? (
              <Skeleton className="h-16 w-24" />
            ) : (
              <>
                <span className="text-5xl font-bold tabular-nums">
                  {fixRate}%
                </span>
                <span className="text-sm text-muted-foreground">
                  of issues resolved
                </span>
                <div className="w-full h-2 rounded-full bg-muted overflow-hidden">
                  <div
                    className="h-full rounded-full bg-emerald-500 transition-all"
                    style={{ width: `${fixRate}%` }}
                  />
                </div>
                <span className="text-xs text-muted-foreground tabular-nums">
                  {resolvedCount} resolved · {openCount} open
                </span>
              </>
            )}
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Grade Distribution</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {reposLoading ? (
              <div className="space-y-3">
                {[...Array(5)].map((_, i) => (
                  <Skeleton key={i} className="h-5 w-full" />
                ))}
              </div>
            ) : gradeDistribution.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-6">
                No graded repositories yet.
              </p>
            ) : (
              gradeDistribution.map(({ grade, count }) => (
                <div key={grade} className="flex items-center gap-3">
                  <div className="w-14 flex-shrink-0">
                    <GradeBadge grade={grade} />
                  </div>
                  <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden">
                    <div
                      className="h-full rounded-full bg-primary transition-all"
                      style={{
                        width: `${Math.round((count / maxGradeCount) * 100)}%`,
                      }}
                    />
                  </div>
                  <span className="w-8 text-right text-xs text-muted-foreground tabular-nums">
                    {count}
                  </span>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
