import { cn } from "@/lib/utils"

interface GradeBadgeProps {
  grade: string | null
  className?: string
}

// Like an energy label: the A grades share success, deepening as they climb;
// then warning, serious and destructive. The label always shows, so two
// grades sharing a hue stay distinct.
const GRADE_STYLES: Record<string, string> = {
  "A+++": "bg-success/25 text-success-ink",
  "A++": "bg-success/22 text-success-ink",
  "A+": "bg-success/18 text-success-ink",
  A: "bg-success/15 text-success-ink",
  B: "bg-success/10 text-success-ink",
  C: "bg-warning/15 text-warning-ink",
  D: "bg-serious/15 text-serious-ink",
  E: "bg-destructive/15 text-destructive",
  F: "bg-destructive text-white",
}

const FALLBACK_STYLE = "bg-muted text-muted-foreground"

export function GradeBadge({ grade, className }: GradeBadgeProps) {
  const display = grade ?? "-"
  const style = GRADE_STYLES[display] ?? FALLBACK_STYLE

  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold",
        style,
        className,
      )}
    >
      {display}
    </span>
  )
}
