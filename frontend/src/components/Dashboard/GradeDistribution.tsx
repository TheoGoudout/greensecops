import type { GradeStat } from "@/client"
import { GradeBadge } from "@/components/GradeBadge"

/**
 * How many scan targets sit at each grade.
 *
 * Magnitude, not identity — so one hue for every bar, sized by count. Rungs
 * nothing landed on are dropped rather than drawn as zero-width bars, which
 * would just be a column of empty rows.
 */
export function GradeDistribution({
  distribution,
  emptyLabel = "Nothing graded yet.",
}: {
  distribution: GradeStat[]
  emptyLabel?: string
}) {
  const present = distribution.filter(({ count }) => count > 0)
  if (present.length === 0) {
    return (
      <p className="text-sm text-muted-foreground text-center py-6">
        {emptyLabel}
      </p>
    )
  }
  const max = Math.max(...present.map((g) => g.count), 1)

  return (
    <div className="space-y-2">
      {present.map(({ grade, count }) => (
        <div key={grade} className="flex items-center gap-3">
          <div className="w-14 flex-shrink-0">
            <GradeBadge grade={grade} />
          </div>
          <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden">
            <div
              className="h-full rounded-full bg-primary transition-all"
              style={{ width: `${Math.round((count / max) * 100)}%` }}
            />
          </div>
          <span className="w-8 text-right text-xs text-muted-foreground tabular-nums">
            {count}
          </span>
        </div>
      ))}
    </div>
  )
}
