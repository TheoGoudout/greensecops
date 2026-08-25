import type { Severity } from "@/client"
import { cn } from "@/lib/utils"

interface SeverityChipProps {
  severity: Severity
  className?: string
}

const SEVERITY_STYLES: Record<Severity, string> = {
  critical:
    "bg-red-100 text-red-800 dark:bg-red-950/60 dark:text-red-300 border border-red-200 dark:border-red-800",
  high: "bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300 border border-orange-200 dark:border-orange-800",
  medium:
    "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300 border border-yellow-200 dark:border-yellow-800",
  low: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300 border border-blue-200 dark:border-blue-800",
  info: "bg-muted text-muted-foreground border border-border",
}

export function SeverityChip({ severity, className }: SeverityChipProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium capitalize",
        SEVERITY_STYLES[severity],
        className,
      )}
    >
      {severity}
    </span>
  )
}
