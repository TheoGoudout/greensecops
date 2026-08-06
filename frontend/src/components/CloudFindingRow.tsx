import type { CloudFindingPublic } from "@/client"
import { FindingRow, SubtitleDetail } from "@/components/FindingRow"

export function CloudFindingRow({ finding }: { finding: CloudFindingPublic }) {
  return (
    <FindingRow
      finding={finding}
      subtitle={
        <>
          {finding.resource_type}: {finding.resource_id}
          {finding.region && <SubtitleDetail>{finding.region}</SubtitleDetail>}
        </>
      }
    />
  )
}
