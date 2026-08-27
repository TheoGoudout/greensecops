import type { AnsibleFindingPublic } from "@/client"
import { FindingRow, SubtitleDetail } from "@/components/FindingRow"

export function AnsibleFindingRow({
  finding,
}: {
  finding: AnsibleFindingPublic
}) {
  return (
    <FindingRow
      finding={finding}
      subtitle={
        <>
          {finding.file_path}
          {finding.task_name && (
            <SubtitleDetail>{finding.task_name}</SubtitleDetail>
          )}
          {finding.line_start && (
            <SubtitleDetail>L{finding.line_start}</SubtitleDetail>
          )}
        </>
      }
    />
  )
}
