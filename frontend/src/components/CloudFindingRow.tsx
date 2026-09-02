import type { CloudFindingPublic } from "@/client"
import { CloudService } from "@/client"
import { FindingRow, SubtitleDetail } from "@/components/FindingRow"
import { useFindingLifecycle } from "@/hooks/useFindingLifecycle"
import { type EngineActionInput, ignoreAction } from "@/lib/engine-actions"

export function CloudFindingRow({
  finding,
  targetState,
}: {
  finding: CloudFindingPublic
  /** What the owning account is doing, from the page's own action input. A
   * running scan is about to replace this finding, so muting it is refused. */
  targetState: EngineActionInput
}) {
  const ignored = finding.status === "ignored"
  const mutation = useFindingLifecycle({
    findingId: finding.id,
    ignored,
    ignore: (cloudFindingId) => CloudService.ignoreFinding({ cloudFindingId }),
    unignore: (cloudFindingId) =>
      CloudService.unignoreFinding({ cloudFindingId }),
    invalidateKeys: [["cloud-findings", finding.cloud_account_id]],
  })

  return (
    <FindingRow
      finding={finding}
      onToggleIgnore={() => mutation.mutate()}
      ignore={ignoreAction(finding.status, {
        ...targetState,
        pending: { ignore: mutation.isPending },
      })}
      subtitle={
        <>
          {finding.resource_type}: {finding.resource_id}
          {finding.region && <SubtitleDetail>{finding.region}</SubtitleDetail>}
        </>
      }
    />
  )
}
