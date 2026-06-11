import { cn } from "@/lib/utils"

interface GradeBadgeProps {
  grade: string | null
  className?: string
}

const GRADE_STYLES: Record<string, string> = {
  "A+++":
    "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  "A++":
    "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  "A+": "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300",
  A: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400",
  B: "bg-lime-100 text-lime-800 dark:bg-lime-900/40 dark:text-lime-300",
  C: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300",
  D: "bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300",
  E: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400",
  F: "bg-red-200 text-red-900 dark:bg-red-950/60 dark:text-red-300",
}

const FALLBACK_STYLE = "bg-muted text-muted-foreground"

export function GradeBadge({ grade, className }: GradeBadgeProps) {
  if (!grade) {
    return (
      <span
        className={cn(
          "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold",
          FALLBACK_STYLE,
          className,
        )}
      >
        —
      </span>
    )
  }

  const style = GRADE_STYLES[grade] ?? FALLBACK_STYLE

  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold",
        style,
        className,
      )}
    >
      {grade}
    </span>
  )
}
