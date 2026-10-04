import type { Severity } from "@/client"
import { cn } from "@/lib/utils"

interface SeverityChipProps {
  severity: Severity
  className?: string
}

const SEVERITY_STYLES: Record<Severity, string> = {
  critical: "bg-destructive/15 text-destructive border border-destructive/30",
  high: "bg-serious/15 text-serious-ink border border-serious/30",
  medium: "bg-warning/15 text-warning-ink border border-warning/30",
  low: "bg-info/15 text-info-ink border border-info/30",
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
