import type { CloudFindingPublic } from "@/client"
import { CloudService } from "@/client"
import { FindingRow, SubtitleDetail } from "@/components/FindingRow"
import { useFindingLifecycle } from "@/hooks/useFindingLifecycle"

export function CloudFindingRow({ finding }: { finding: CloudFindingPublic }) {
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
      ignorePending={mutation.isPending}
      subtitle={
        <>
          {finding.resource_type}: {finding.resource_id}
          {finding.region && <SubtitleDetail>{finding.region}</SubtitleDetail>}
        </>
      }
    />
  )
}
