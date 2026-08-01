import { Activity } from "lucide-react"
import type { DockerRuntimeFindingPublic } from "@/client"
import { CategoryIcon } from "@/components/CategoryIcon"
import { RuleSlugChip } from "@/components/RuleSlugChip"
import { SeverityChip } from "@/components/SeverityChip"
import { Checkbox } from "@/components/ui/checkbox"

interface DockerRuntimeFindingRowProps {
  finding: DockerRuntimeFindingPublic
  selected: boolean
  onToggle: () => void
  selectable: boolean
}

/**
 * One measured finding from Docker build/container telemetry.
 *
 * Distinct from {@link DockerFindingRow}: a static finding says the file is
 * wrong, this says what the container actually did. The evidence line carries
 * the measurement itself, so it is given the same weight as the
 * recommendation rather than being tucked away as a file path.
 *
 * Severity and category come from the rule catalog and are absent when a Rego
 * rule shipped without a seed entry — the row still renders, because a
 * measurement with no catalog row is still a real observation.
 */
export function DockerRuntimeFindingRow({
  finding,
  selected,
  onToggle,
  selectable,
}: DockerRuntimeFindingRowProps) {
  return (
    <div className="flex items-start gap-3 px-6 py-4">
      {selectable ? (
        <Checkbox
          checked={selected}
          onCheckedChange={onToggle}
          aria-label={`Select ${finding.rule_slug}`}
          className="mt-1 shrink-0"
        />
      ) : (
        <Activity className="mt-0.5 shrink-0 h-4 w-4 text-amber-600 dark:text-amber-400" />
      )}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          {finding.category && (
            <CategoryIcon category={finding.category} className="text-base" />
          )}
          {finding.severity && <SeverityChip severity={finding.severity} />}
          <RuleSlugChip>{finding.rule_slug}</RuleSlugChip>
          <span className="text-sm break-words min-w-0">
            {finding.rule_title ?? finding.recommendation}
          </span>
        </div>
        <p className="text-xs font-mono text-muted-foreground mt-1 break-words">
          {finding.evidence}
        </p>
        {finding.rule_title && (
          <p className="text-xs text-muted-foreground mt-1 break-words">
            {finding.recommendation}
          </p>
        )}
      </div>
    </div>
  )
}
