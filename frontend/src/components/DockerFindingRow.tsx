import type { DockerFindingPublic } from "@/client"
import { CategoryIcon } from "@/components/CategoryIcon"
import { RuleSlugChip } from "@/components/RuleSlugChip"
import { SeverityChip } from "@/components/SeverityChip"

interface DockerFindingRowProps {
  finding: DockerFindingPublic
}

/**
 * Read-only, mirroring TerraformFindingRow: the Docker engine has no
 * per-finding lifecycle route either, so there's no ignore/mute action —
 * findings resolve on rescan when the underlying problem goes away.
 */
export function DockerFindingRow({ finding }: DockerFindingRowProps) {
  // A Compose rule names the service it fired on, a Dockerfile rule the build
  // stage; a file-level rule (a missing OCI label) names neither and falls
  // back to the path alone.
  const locator = finding.service_name ?? finding.stage_name

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
          {finding.file_path}
          {locator && (
            <span className="text-muted-foreground/70"> · {locator}</span>
          )}
          {finding.line_start && (
            <span className="text-muted-foreground/70">
              {" "}
              · L{finding.line_start}
            </span>
          )}
        </p>
      </div>
    </div>
  )
}
