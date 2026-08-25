import type { ReactNode } from "react"
import type { Category, Severity } from "@/client"
import { CategoryIcon } from "@/components/CategoryIcon"
import { RuleSlugChip } from "@/components/RuleSlugChip"
import { SeverityChip } from "@/components/SeverityChip"

/**
 * The fields every engine's finding carries. Structural typing means
 * TerraformFindingPublic, DockerFindingPublic and CloudFindingPublic all
 * satisfy this without being named here.
 */
interface CommonFinding {
  severity: Severity
  category: Category
  rule_slug: string
  message: string
}

/**
 * One rule violation from the Terraform, Docker or cloud engine.
 *
 * `subtitle` is the muted second line naming *where* the violation is, and is
 * the only thing that differs between the three: Terraform names a resource
 * address, Docker a file plus service or stage, cloud a resource type and id.
 *
 * Read-only by design: none of the three has a per-finding lifecycle route
 * yet, so unlike {@link IssueRow} there is no ignore/mute action — findings
 * resolve on the next scan when the underlying problem goes away.
 */
export function FindingRow({
  finding,
  subtitle,
}: {
  finding: CommonFinding
  subtitle: ReactNode
}) {
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
          {subtitle}
        </p>
      </div>
    </div>
  )
}

/** Dimmed trailing detail on a subtitle line, e.g. " · L42". */
export function SubtitleDetail({ children }: { children: ReactNode }) {
  return <span className="text-muted-foreground/70"> · {children}</span>
}
