import { Link } from "@tanstack/react-router"
import type { EngineOverview } from "@/client"
import { SeverityBar } from "@/components/Dashboard/SeverityBar"
import { GradeBadge } from "@/components/GradeBadge"
import { ENGINE_META } from "@/lib/engine-meta"
import { relativeTime } from "@/lib/format"

const COLUMNS =
  "grid-cols-[minmax(7rem,1.4fr)_4rem_3.5rem_4.5rem_5rem_minmax(5rem,1fr)_5rem]"

/**
 * Every analysis engine, side by side — the one widget that answers "which of
 * these is in the worst shape" without expanding anything.
 *
 * A table rather than a chart on purpose: seven measures across four engines
 * is a grid of numbers, and four categorical series on a plot would need hues
 * the app's chart tokens cannot separate safely in dark mode.
 */
export function EngineOverviewTable({
  engines,
}: {
  engines: EngineOverview[]
}) {
  return (
    <div className="overflow-x-auto">
      <div className="min-w-[46rem]">
        <div
          className={`grid ${COLUMNS} items-center px-6 py-2 border-b text-xs font-medium text-muted-foreground uppercase tracking-wide gap-3`}
        >
          <span>Engine</span>
          <span>Grade</span>
          <span className="text-right">Score</span>
          <span className="text-right">Targets</span>
          <span className="text-right">Open</span>
          <span>Severity</span>
          <span className="text-right">Last scan</span>
        </div>
        <div className="divide-y">
          {engines.map((engine) => {
            const meta = ENGINE_META[engine.engine]
            const Icon = meta.icon
            const { coverage, score, findings, freshness } = engine
            return (
              <Link
                key={engine.engine}
                to={meta.to}
                data-testid={`engine-row-${engine.engine}`}
                className={`grid ${COLUMNS} items-center px-6 py-3 gap-3 hover:bg-muted/50 transition-colors`}
              >
                <span className="flex items-center gap-2 min-w-0">
                  <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <span className="text-sm font-medium truncate">
                    {meta.label}
                  </span>
                </span>
                <GradeBadge grade={score.grade} />
                <span className="text-xs text-right tabular-nums text-muted-foreground">
                  {score.avg_score != null ? score.avg_score.toFixed(0) : "—"}
                </span>
                <span className="text-xs text-right tabular-nums text-muted-foreground">
                  {coverage.scanned}
                  <span className="opacity-60">/{coverage.total}</span>
                </span>
                <span className="text-right text-sm tabular-nums">
                  <span className="font-medium">{findings.open}</span>
                  {findings.critical_open > 0 && (
                    <span className="ml-1 text-xs text-red-600 dark:text-red-400">
                      {findings.critical_open} crit
                    </span>
                  )}
                </span>
                <SeverityBar stats={findings.by_severity} />
                <span className="text-xs text-right text-muted-foreground">
                  {relativeTime(freshness.last_completed_scan_at)}
                </span>
              </Link>
            )
          })}
        </div>
      </div>
    </div>
  )
}
