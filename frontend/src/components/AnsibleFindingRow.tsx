import type { AnsibleFindingPublic } from "@/client"
import { FindingRow, SubtitleDetail } from "@/components/FindingRow"

export function AnsibleFindingRow({
  finding,
}: {
  finding: AnsibleFindingPublic
}) {
  // Most Ansible rules fire on a task, and the task's name is the locator a
  // reader recognises. A rule about the file itself — an unpinned galaxy
  // requirement, a credential in a variables file — names no task and falls
  // back to the path alone.
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
