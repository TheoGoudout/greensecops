import { AlertCircle, CheckCircle2, Crosshair, Wrench } from "lucide-react"
import type { EngineOverview } from "@/client"
import { GradeDistribution } from "@/components/Dashboard/GradeDistribution"
import { SeverityBar } from "@/components/Dashboard/SeverityBar"
import { StatCard } from "@/components/Dashboard/StatCard"
import { TopRulesList } from "@/components/Dashboard/TopRulesList"
import { GradeBadge } from "@/components/GradeBadge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ENGINE_META, relativeTime } from "@/lib/engine-meta"

/**
 * The widget set every engine section shows, driven entirely by props.
 *
 * One component rather than three near-copies: the four engines return the
 * same aggregate shape from `/overview/`, so the only genuine variation is
 * whether a fix pipeline exists — cloud posture has none, and shows no
 * fix-rate card rather than a zeroed one.
 */
export function EngineDetail({ engine }: { engine: EngineOverview }) {
  const meta = ENGINE_META[engine.engine]
  const { coverage, score, findings, fixes, freshness, top_rules } = engine
  const addressed = fixes
    ? fixes.ready + fixes.delivered + fixes.landed + fixes.in_progress
    : 0
  const fixRate =
    fixes && findings.open > 0
      ? Math.round((addressed / findings.open) * 100)
      : 0

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          icon={meta.icon}
          title="Targets scanned"
          value={`${coverage.scanned}/${coverage.total}`}
          hint={
            coverage.never_scanned > 0
              ? `${coverage.never_scanned} never scanned`
              : "all targets covered"
          }
          loading={false}
        />
        <StatCard
          icon={Crosshair}
          title="Average score"
          value={score.avg_score != null ? score.avg_score.toFixed(0) : "—"}
          hint={`across ${score.scored_targets} scored target${
            score.scored_targets === 1 ? "" : "s"
          }`}
          loading={false}
          accessory={<GradeBadge grade={score.grade} />}
        />
        <StatCard
          icon={AlertCircle}
          title="Open findings"
          value={findings.open}
          hint={
            findings.critical_open > 0
              ? `${findings.critical_open} critical`
              : "none critical"
          }
          loading={false}
        />
        {fixes ? (
          <StatCard
            icon={Wrench}
            title="Being fixed"
            value={`${fixRate}%`}
            hint={`${fixes.ready} ready · ${fixes.delivered} on a PR · ${fixes.landed} landed`}
            loading={false}
          />
        ) : (
          <StatCard
            icon={CheckCircle2}
            title="Resolved findings"
            value={findings.resolved}
            // Cloud posture has no fix pipeline at all, so there is no fix rate
            // to show here — saying so beats a card of zeroes.
            hint="cloud posture has no fix pipeline"
            loading={false}
          />
        )}
      </div>

      {coverage.latest_scan_failed > 0 && (
        <p className="text-xs text-amber-700 dark:text-amber-400">
          {coverage.latest_scan_failed} target
          {coverage.latest_scan_failed === 1 ? "'s" : "s'"} most recent scan
          failed — the grade above is from the last scan that completed.
        </p>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card className="lg:col-span-2">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm flex items-center justify-between">
              Most common findings
              <span className="text-xs font-normal text-muted-foreground">
                last scan {relativeTime(freshness.last_completed_scan_at)}
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <TopRulesList
              rules={top_rules}
              emptyLabel={
                coverage.scanned === 0
                  ? "Nothing scanned yet."
                  : "No open findings — all clear."
              }
            />
          </CardContent>
        </Card>

        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">Grade distribution</CardTitle>
            </CardHeader>
            <CardContent>
              <GradeDistribution
                distribution={score.by_grade}
                emptyLabel="No target has been graded yet."
              />
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">Open by severity</CardTitle>
            </CardHeader>
            <CardContent>
              {findings.open === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-2">
                  Nothing open.
                </p>
              ) : (
                <SeverityBar stats={findings.by_severity} withLegend />
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
