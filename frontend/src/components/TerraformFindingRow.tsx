import type { TerraformFindingPublic } from "@/client"
import { FindingRow, SubtitleDetail } from "@/components/FindingRow"

export function TerraformFindingRow({
  finding,
}: {
  finding: TerraformFindingPublic
}) {
  return (
    <FindingRow
      finding={finding}
      subtitle={
        <>
          {finding.resource_address ?? finding.file_path}
          {finding.line_start && (
            <SubtitleDetail>L{finding.line_start}</SubtitleDetail>
          )}
        </>
      }
    />
  )
}
