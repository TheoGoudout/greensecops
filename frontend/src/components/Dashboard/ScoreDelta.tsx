import { TrendingDown, TrendingUp } from "lucide-react"
import { cn } from "@/lib/utils"

/** A signed score change. Sub-point moves render as a dash — noise, not news. */
export function ScoreDelta({ value }: { value: number }) {
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
