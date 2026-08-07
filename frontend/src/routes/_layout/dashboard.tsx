import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  AlertCircle,
  Boxes,
  Container,
  CreditCard,
  Gauge,
  Layers,
  PieChart,
  Radar,
  Workflow,
  Wrench,
} from "lucide-react"
import { useMemo, useState } from "react"
import type { EngineOverview, IssueCategory, OverviewSection } from "@/client"
import {
  AnalysesService,
  BillingService,
  IssuesService,
  OverviewService,
  RepositoriesService,
} from "@/client"
import { CategoryHealthRadar } from "@/components/CategoryHealthRadar"
import { WidgetPagination } from "@/components/Common/WidgetPagination"
import { CategoryEngineHeatmap } from "@/components/Dashboard/CategoryEngineHeatmap"
import { CollapsibleSection } from "@/components/Dashboard/CollapsibleSection"
import { EngineDetail } from "@/components/Dashboard/EngineDetail"
import { EngineOverviewTable } from "@/components/Dashboard/EngineOverviewTable"
import { GradeDistribution } from "@/components/Dashboard/GradeDistribution"
import { ScoreDelta } from "@/components/Dashboard/ScoreDelta"
import { SeverityBar } from "@/components/Dashboard/SeverityBar"
import { StatCard } from "@/components/Dashboard/StatCard"
import { UsageBar } from "@/components/Dashboard/UsageBar"
import { useCollapsedSections } from "@/components/Dashboard/useCollapsedSections"
import { GradeBadge } from "@/components/GradeBadge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { SECTION_ORDER } from "@/lib/engine-meta"
import { GRADE_ORDER, worstGrade } from "@/lib/grades"
import { ISSUE_CATEGORIES } from "@/lib/issue-constants"

export const Route = createFileRoute("/_layout/dashboard")({
  component: Dashboard,
  head: () => ({
    meta: [{ title: "Dashboard - GreenSecOps" }],
  }),
})

const REPO_HEALTH_PAGE_SIZE = 8
const DEFAULT_TOGGLED_REPO_COUNT = 8

const TIER_LABELS: Record<string, string> = {
  free: "Free",
  starter: "Starter",
  pro: "Pro",
  ultimate: "Ultimate",
  open_source: "Open Source",
}

const SECTION_ICON: Record<OverviewSection, typeof Workflow> = {
  ci: Workflow,
  docker: Container,
  infra: Boxes,
}

type TierLimits = {
  tier: string
  limits: Record<string, number | null>
}

/** The chips a collapsed section still shows, so folding costs no signal. */
function SectionSummary({ engines }: { engines: EngineOverview[] }) {
  const open = engines.reduce((sum, e) => sum + e.findings.open, 0)
  const critical = engines.reduce((sum, e) => sum + e.findings.critical_open, 0)
  // The Infrastructure section holds two engines; its headline is the worse of
  // their grades, matching how the Infrastructure page already rolls a repo's
  // targets up to one grade.
  const grade = worstGrade(engines.map((e) => e.score.grade))

  return (
    <>
      <GradeBadge grade={grade} />
      <span className="text-xs text-muted-foreground tabular-nums">
        <span className="font-medium text-foreground">{open}</span> open
      </span>
      {critical > 0 && (
        <span className="text-xs font-medium text-red-600 dark:text-red-400 tabular-nums">
          {critical} critical
        </span>
      )}
    </>
  )
}

function Dashboard() {
  // The one exact, SQL-aggregated view of every engine. Everything in the
  // top section and the per-engine sections comes from here; the queries
  // below only back the CI section's repo-level widgets.
  const { data: overview, isLoading: overviewLoading } = useQuery({
    queryKey: ["overview"],
    queryFn: () => OverviewService.getOverview(),
  })

  const { data: repos, isLoading: reposLoading } = useQuery({
    queryKey: ["repositories"],
    queryFn: () => RepositoriesService.listRepositories({ limit: 200 }),
  })

  const { data: analyses, isLoading: analysesLoading } = useQuery({
    queryKey: ["analyses", "recent"],
    queryFn: () => AnalysesService.listAnalyses({ limit: 200 }),
  })

  // Per-repo category breakdown for the CI radar. /overview/ aggregates per
  // engine, not per repo, so this stays the source for that one widget.
  const { data: issueStats, isLoading: issueStatsLoading } = useQuery({
    queryKey: ["issues", "stats"],
    queryFn: () => IssuesService.getIssueStats(),
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
  const { collapsed, toggle } = useCollapsedSections()

  const engines = overview?.engines ?? []
  const totals = overview?.totals
  const enginesBySection = useMemo(() => {
    const map = new Map<OverviewSection, EngineOverview[]>()
    for (const engine of engines) {
      map.set(engine.section, [...(map.get(engine.section) ?? []), engine])
    }
    return map
  }, [engines])

  const totalOpen = totals?.open_findings ?? 0
  const totalResolved = totals?.resolved_findings ?? 0
  const fixRate =
    totalOpen + totalResolved > 0
      ? Math.round((totalResolved / (totalOpen + totalResolved)) * 100)
      : 0
  const coveragePct =
    totals && totals.targets > 0
      ? Math.round(
          ((totals.targets - totals.never_scanned_targets) / totals.targets) *
            100,
        )
      : 0

  // ─── CI section: per-repo widgets ──────────────────────────────────────────

  const repoCategoryHealth = useMemo(() => {
    if (!repos || !issueStats?.by_repo) return []

    const statsByRepoId = new Map(issueStats.by_repo.map((r) => [r.repo_id, r]))

    // listRepositories returns grade "N/A" (never null) for a repo with no
    // CI workflows at all — nothing to plot, so it would only ever render
    // an uninformative full-100 pentagon.
    return repos
      .filter((repo) => repo.grade !== "N/A")
      .map((repo) => {
        const repoStats = statsByRepoId.get(repo.id)
        const categoryByName = new Map(
          repoStats?.categories?.map((c) => [c.category, c]) ?? [],
        )
        let totalOpenForRepo = 0
        const values = Object.fromEntries(
          ISSUE_CATEGORIES.map((category) => {
            const categoryStat = categoryByName.get(category)
            totalOpenForRepo += categoryStat?.open ?? 0
            const score =
              categoryStat?.score ?? repoStats?.score ?? repo.avg_score ?? 100
            return [category, score]
          }),
        ) as Record<IssueCategory, number>
        return {
          id: repo.id,
          name: repo.full_name,
          values,
          totalOpen: totalOpenForRepo,
        }
      })
      .sort((a, b) => b.totalOpen - a.totalOpen)
  }, [repos, issueStats])

  const [toggledRepoIds, setToggledRepoIds] = useState<Set<string> | null>(null)
  const defaultToggledRepoIds = useMemo(
    () =>
      new Set(
        repoCategoryHealth
          .slice(0, DEFAULT_TOGGLED_REPO_COUNT)
          .map((s) => s.id),
      ),
    [repoCategoryHealth],
  )
  const effectiveToggledRepoIds = toggledRepoIds ?? defaultToggledRepoIds
  const toggleRepo = (repoId: string) => {
    setToggledRepoIds((prev) => {
      const base = prev ?? defaultToggledRepoIds
      const next = new Set(base)
      if (next.has(repoId)) {
        next.delete(repoId)
      } else {
        next.add(repoId)
      }
      return next
    })
  }

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

  const [repoHealthPageIndex, setRepoHealthPageIndex] = useState(0)
  const repoHealthPageCount = Math.ceil(
    repoHealthData.length / REPO_HEALTH_PAGE_SIZE,
  )
  const clampedRepoHealthPageIndex = Math.min(
    repoHealthPageIndex,
    Math.max(repoHealthPageCount - 1, 0),
  )
  const pagedRepoHealthData = repoHealthData.slice(
    clampedRepoHealthPageIndex * REPO_HEALTH_PAGE_SIZE,
    (clampedRepoHealthPageIndex + 1) * REPO_HEALTH_PAGE_SIZE,
  )

  const billingLoading = subscriptionLoading || tierLimitsLoading
  const limits = tierLimits?.limits

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
        <p className="text-muted-foreground">
          Security posture across every analysis type — CI workflows, Docker and
          infrastructure.
        </p>
      </div>

      {/* ─── All analysis types ─────────────────────────────────────────── */}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          icon={Gauge}
          title="Overall score"
          value={totals?.avg_score != null ? totals.avg_score.toFixed(0) : "—"}
          hint="mean of each engine's average"
          loading={overviewLoading}
          accessory={<GradeBadge grade={totals?.grade ?? null} />}
        />
        <StatCard
          icon={AlertCircle}
          title="Open findings"
          value={totalOpen}
          hint={`${totals?.critical_open ?? 0} critical, all engines`}
          loading={overviewLoading}
        />
        <StatCard
          icon={Wrench}
          title="Fix rate"
          value={`${fixRate}%`}
          hint={`${totalResolved} of ${totalOpen + totalResolved} resolved`}
          loading={overviewLoading}
        />
        <StatCard
          icon={Layers}
          title="Scan coverage"
          value={`${coveragePct}%`}
          hint={`${totals?.targets ?? 0} targets, ${
            totals?.never_scanned_targets ?? 0
          } never scanned`}
          loading={overviewLoading}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card className="lg:col-span-2">
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Layers className="h-4 w-4 text-muted-foreground" />
              Analysis types
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0 pb-2">
            {overviewLoading ? (
              <div className="flex flex-col gap-2 p-6">
                {[...Array(4)].map((_, i) => (
                  <Skeleton key={i} className="h-10 w-full" />
                ))}
              </div>
            ) : (
              <EngineOverviewTable engines={engines} />
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

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card className="lg:col-span-2">
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <PieChart className="h-4 w-4 text-muted-foreground" />
              Where the findings are
            </CardTitle>
          </CardHeader>
          <CardContent>
            {overviewLoading ? (
              <div className="space-y-3">
                {[...Array(5)].map((_, i) => (
                  <Skeleton key={i} className="h-8 w-full" />
                ))}
              </div>
            ) : (
              <CategoryEngineHeatmap engines={engines} />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Open by severity</CardTitle>
          </CardHeader>
          <CardContent>
            {overviewLoading ? (
              <div className="space-y-3">
                {[...Array(4)].map((_, i) => (
                  <Skeleton key={i} className="h-5 w-full" />
                ))}
              </div>
            ) : totalOpen === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-6">
                No open findings on any engine.
              </p>
            ) : (
              <SeverityBar stats={totals?.by_severity ?? []} withLegend />
            )}
          </CardContent>
        </Card>
      </div>

      {/* ─── Per-type detail ────────────────────────────────────────────── */}

      {SECTION_ORDER.map((section) => {
        const sectionEngines = enginesBySection.get(section) ?? []
        if (overviewLoading) {
          return <Skeleton key={section} className="h-24 w-full" />
        }
        if (sectionEngines.length === 0) return null

        const isCi = section === "ci"
        const title = isCi
          ? "CI workflows"
          : section === "docker"
            ? "Docker"
            : "Infrastructure"
        const description = isCi
          ? "GitHub Actions workflow files, per repository"
          : section === "docker"
            ? "Dockerfiles and Compose files, per target folder"
            : "Terraform roots and live cloud posture"

        return (
          <CollapsibleSection
            key={section}
            testId={`section-${section}`}
            icon={SECTION_ICON[section]}
            title={title}
            description={description}
            open={!collapsed.has(section)}
            onToggle={() => toggle(section)}
            summary={<SectionSummary engines={sectionEngines} />}
          >
            {sectionEngines.map((engine) => (
              <div key={engine.engine} className="flex flex-col gap-6">
                {sectionEngines.length > 1 && (
                  <h3 className="text-sm font-semibold text-muted-foreground">
                    {engine.label}
                  </h3>
                )}
                <EngineDetail engine={engine} />
              </div>
            ))}

            {/* Repo-level CI widgets: /overview/ aggregates per engine, so
                these stay backed by the repository and issue-stats queries. */}
            {isCi && (
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <Card className="lg:col-span-2">
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm flex items-center justify-between">
                      Repository health
                      <span className="text-xs font-normal text-muted-foreground">
                        first vs. latest score
                      </span>
                    </CardTitle>
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
                        {/* Five columns do not fit a phone. Scroll the table
                            inside its own container rather than letting the
                            whole page scroll sideways. */}
                        <div className="overflow-x-auto">
                          <div className="min-w-[30rem]">
                            <div className="grid grid-cols-[1fr_3.5rem_4rem_4rem_4rem] items-center px-6 py-2 border-b text-xs font-medium text-muted-foreground uppercase tracking-wide gap-3">
                              <span>Repository</span>
                              <span>Grade</span>
                              <span className="text-right">First</span>
                              <span className="text-right">Latest</span>
                              <span className="text-right">Delta</span>
                            </div>
                            <div className="divide-y">
                              {pagedRepoHealthData.map(
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
                          </div>
                        </div>
                        <WidgetPagination
                          pageIndex={clampedRepoHealthPageIndex}
                          pageSize={REPO_HEALTH_PAGE_SIZE}
                          totalItems={repoHealthData.length}
                          onPrevious={() =>
                            setRepoHealthPageIndex((i) => Math.max(i - 1, 0))
                          }
                          onNext={() =>
                            setRepoHealthPageIndex((i) =>
                              Math.min(i + 1, repoHealthPageCount - 1),
                            )
                          }
                        />
                      </>
                    )}
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm">
                      Grades across repositories
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    {reposLoading ? (
                      <div className="space-y-3">
                        {[...Array(5)].map((_, i) => (
                          <Skeleton key={i} className="h-5 w-full" />
                        ))}
                      </div>
                    ) : (
                      <GradeDistribution
                        distribution={repoGradeDistribution(repos)}
                        emptyLabel="No graded repositories yet."
                      />
                    )}
                  </CardContent>
                </Card>

                <Card className="lg:col-span-3">
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <Radar className="h-4 w-4 text-muted-foreground" />
                      Category health by repository
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    {issueStatsLoading || reposLoading ? (
                      <div className="space-y-3">
                        {[...Array(5)].map((_, i) => (
                          <Skeleton key={i} className="h-5 w-full" />
                        ))}
                      </div>
                    ) : (issueStats?.total_open ?? 0) === 0 ||
                      repoCategoryHealth.length === 0 ? (
                      <p className="text-sm text-muted-foreground text-center py-6">
                        No open issues — nothing to show yet.
                      </p>
                    ) : (
                      <CategoryHealthRadar
                        categories={ISSUE_CATEGORIES}
                        series={repoCategoryHealth}
                        toggledIds={effectiveToggledRepoIds}
                        onToggle={toggleRepo}
                      />
                    )}
                  </CardContent>
                </Card>
              </div>
            )}
          </CollapsibleSection>
        )
      })}
    </div>
  )
}

/** Grade counts across repositories, in ladder order. */
function repoGradeDistribution(
  repos: { grade?: string | null }[] | undefined,
): { grade: string; count: number }[] {
  if (!repos) return []
  const counts = new Map<string, number>()
  for (const repo of repos) {
    // "N/A" and "-" are placeholders for "nothing to grade", not grades.
    if (repo.grade && repo.grade !== "N/A" && repo.grade !== "-") {
      counts.set(repo.grade, (counts.get(repo.grade) ?? 0) + 1)
    }
  }
  return GRADE_ORDER.map((grade) => ({
    grade,
    count: counts.get(grade) ?? 0,
  })).filter(({ count }) => count > 0)
}
