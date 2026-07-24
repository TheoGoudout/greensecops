import type { TerraformFindingPublic } from "@/client"
import { CategoryIcon } from "@/components/CategoryIcon"
import { RuleSlugChip } from "@/components/RuleSlugChip"
import { SeverityChip } from "@/components/SeverityChip"

interface TerraformFindingRowProps {
  finding: TerraformFindingPublic
}

/**
 * Read-only — unlike IssueRow there's no ignore/mute action yet: the
 * Terraform engine has no per-finding lifecycle route (Phase 1 only ships
 * list/resolve-on-rescan, not user-initiated dismissal).
 */
export function TerraformFindingRow({ finding }: TerraformFindingRowProps) {
  return (
    <div className="flex items-start gap-3 px-6 py-4">
      <CategoryIcon
        category={finding.category}
        className="mt-0.5 shrink-0 text-base"
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <SeverityChip severity={finding.severity} />
          <RuleSlugChip>{finding.rule_slug}</RuleSlugChip>
          <span className="text-sm break-words min-w-0">{finding.message}</span>
        </div>
        <p className="text-xs text-muted-foreground mt-0.5 font-mono truncate">
          {finding.resource_address ?? finding.file_path}
          {finding.resource_address && (
            <span className="text-muted-foreground/70">
              {" "}
              · {finding.file_path}
            </span>
          )}
        </p>
      </div>
    </div>
  )
}
