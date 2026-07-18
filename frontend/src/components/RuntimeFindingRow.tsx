import { Activity } from "lucide-react"
import type { DynamicEnrichmentPublic } from "@/client"

interface RuntimeFindingRowProps {
  finding: DynamicEnrichmentPublic
}

/**
 * One runtime-telemetry finding. Deliberately distinct from {@link IssueRow}:
 * runtime findings carry no severity/status/fix lifecycle, so they render as
 * low-key recommendations with an amber "Runtime" badge rather than as static
 * issues the user can ignore or fix.
 */
export function RuntimeFindingRow({ finding }: RuntimeFindingRowProps) {
  return (
    <div className="flex items-start gap-3 px-6 py-4">
      <Activity className="mt-0.5 shrink-0 h-4 w-4 text-amber-600 dark:text-amber-400" />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-amber-100 text-amber-800 dark:bg-amber-950/50 dark:text-amber-300">
            Runtime
          </span>
          <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-mono bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300">
            {finding.rule_slug}
          </span>
          <span className="text-sm break-words min-w-0">
            {finding.recommendation}
          </span>
        </div>
        <p className="text-xs text-muted-foreground mt-0.5 font-mono break-words">
          {finding.evidence}
          {finding.workflow_run_id != null && (
            <span className="ml-2">· run #{finding.workflow_run_id}</span>
          )}
        </p>
      </div>
    </div>
  )
}
