import { cn } from "@/lib/utils"

/**
 * A single quota against its limit.
 *
 * A meter, not a chart: the fill carries severity as the quota fills up, and
 * an unmetered plan shows a stub rather than a full bar, so "unlimited" never
 * reads as "at capacity".
 */
export function UsageBar({
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
