import type { CloudFindingPublic } from "@/client"
import { CategoryIcon } from "@/components/CategoryIcon"
import { RuleSlugChip } from "@/components/RuleSlugChip"
import { SeverityChip } from "@/components/SeverityChip"

interface CloudFindingRowProps {
  finding: CloudFindingPublic
}

/**
 * Read-only, mirrors TerraformFindingRow — the Cloud engine has no
 * per-finding lifecycle route yet either (list/resolve-on-rescan only).
 */
export function CloudFindingRow({ finding }: CloudFindingRowProps) {
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
          {finding.resource_type}: {finding.resource_id}
          {finding.region && (
            <span className="text-muted-foreground/70">
              {" "}
              · {finding.region}
            </span>
          )}
        </p>
      </div>
    </div>
  )
}
