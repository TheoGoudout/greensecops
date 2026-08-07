import type { SeverityStat } from "@/client"
import { SEVERITY_FILL } from "@/lib/engine-meta"
import { SEVERITY_ORDER } from "@/lib/severity"
import { cn } from "@/lib/utils"

/**
 * The severity composition of a set of open findings.
 *
 * Part-to-whole over an ordered scale, so the segments always run
 * critical → info regardless of which severities are present. Two details are
 * load-bearing rather than cosmetic:
 *
 * - Segments are separated by a 2px gap in the surface color, not a border.
 *   White does the separating; a stroke would add ink that isn't data.
 * - `withLegend` renders the counts as text beneath. Severity uses the status
 *   palette, whose neighbouring hues (red/orange, yellow/blue) are close
 *   enough that color must never be the only channel — the legend is what
 *   makes the bar readable without it, and it doubles as the table view.
 */
export function SeverityBar({
  stats,
  withLegend = false,
  className,
}: {
  stats: SeverityStat[]
  withLegend?: boolean
  className?: string
}) {
  const bySeverity = new Map(stats.map((s) => [s.severity, s.open]))
  const segments = SEVERITY_ORDER.map((severity) => ({
    severity,
    open: bySeverity.get(severity) ?? 0,
  })).filter(({ open }) => open > 0)
  const total = segments.reduce((sum, s) => sum + s.open, 0)

  if (total === 0) {
    return (
      <div className={cn("flex items-center", className)}>
        <div className="h-1.5 w-full rounded-full bg-muted" />
      </div>
    )
  }

  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <div
        className="flex h-1.5 w-full gap-0.5"
        role="img"
        aria-label={segments
          .map(({ severity, open }) => `${open} ${severity}`)
          .join(", ")}
      >
        {segments.map(({ severity, open }) => (
          <div
            key={severity}
            title={`${open} ${severity}`}
            // Square by default, rounded only at the two outer ends: a
            // fully-rounded segment reads as its own pill, so a narrow slice
            // turns into a stray dot instead of part of one divided bar.
            className={cn(
              "h-full first:rounded-l-full last:rounded-r-full",
              SEVERITY_FILL[severity],
            )}
            style={{ width: `${(open / total) * 100}%` }}
          />
        ))}
      </div>
      {withLegend && (
        <ul className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {segments.map(({ severity, open }) => (
            <li
              key={severity}
              className="flex items-center gap-1.5 text-xs text-muted-foreground"
            >
              <span
                aria-hidden="true"
                className={cn(
                  "h-2 w-2 shrink-0 rounded-full",
                  SEVERITY_FILL[severity],
                )}
              />
              <span className="tabular-nums font-medium text-foreground">
                {open}
              </span>
              <span className="capitalize">{severity}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
