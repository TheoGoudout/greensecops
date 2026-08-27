import { Bell, BellOff, Loader2 } from "lucide-react"
import type { ReactNode } from "react"
import type { Category, FindingStatus, Severity } from "@/client"
import { CategoryIcon } from "@/components/CategoryIcon"
import { RuleSlugChip } from "@/components/RuleSlugChip"
import { SeverityChip } from "@/components/SeverityChip"
import { StatusPill } from "@/components/StatusPill"
import { Button } from "@/components/ui/button"
import { findingStatusColor, findingStatusLabel } from "@/lib/status-colors"

/**
 * The fields every engine's finding carries. Structural typing means
 * TerraformFindingPublic, DockerFindingPublic, CloudFindingPublic and
 * AnsibleFindingPublic all satisfy this without being named here.
 */
interface CommonFinding {
  severity: Severity
  category: Category
  rule_slug: string
  message: string
  status?: FindingStatus
}

/**
 * One rule violation from the Terraform, Docker, Cloud or Ansible engine.
 *
 * `subtitle` is the muted second line naming *where* the violation is, and is
 * the only thing that differs between the engines: Terraform names a resource
 * address, Docker/Ansible a file plus a locator, cloud a resource type and id.
 *
 * The ignore/unignore action is optional (`onToggleIgnore` undefined) so a
 * caller that hasn't wired lifecycle support yet keeps today's read-only
 * rendering — mirrors how `IssueRow`'s checkbox is optional via
 * `onCheckedChange`.
 */
export function FindingRow({
  finding,
  subtitle,
  onToggleIgnore,
  ignorePending = false,
}: {
  finding: CommonFinding
  subtitle: ReactNode
  onToggleIgnore?: () => void
  ignorePending?: boolean
}) {
  const ignored = finding.status === "ignored"
  return (
    <div
      className={`flex items-start gap-3 px-6 py-4 ${ignored ? "opacity-60" : ""}`}
    >
      <CategoryIcon
        category={finding.category}
        className="mt-0.5 shrink-0 text-base"
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <SeverityChip severity={finding.severity} />
          <RuleSlugChip>{finding.rule_slug}</RuleSlugChip>
          {finding.status && finding.status !== "open" && (
            <StatusPill
              colorClass={findingStatusColor(finding.status)}
              className="inline-flex items-center capitalize"
            >
              {findingStatusLabel(finding.status)}
            </StatusPill>
          )}
          <span className="text-sm break-words min-w-0">{finding.message}</span>
        </div>
        <p className="text-xs text-muted-foreground mt-0.5 font-mono truncate">
          {subtitle}
        </p>
      </div>
      {onToggleIgnore && (
        <Button
          variant="ghost"
          size="sm"
          className="h-7 shrink-0 gap-1.5 text-xs text-muted-foreground"
          onClick={onToggleIgnore}
          disabled={ignorePending}
          title={ignored ? "Unignore this finding" : "Ignore this finding"}
        >
          {ignorePending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : ignored ? (
            <Bell className="h-3.5 w-3.5" />
          ) : (
            <BellOff className="h-3.5 w-3.5" />
          )}
          {ignored ? "Unignore" : "Ignore"}
        </Button>
      )}
    </div>
  )
}

/** Dimmed trailing detail on a subtitle line, e.g. " · L42". */
export function SubtitleDetail({ children }: { children: ReactNode }) {
  return <span className="text-muted-foreground/70"> · {children}</span>
}
