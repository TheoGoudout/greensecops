import type { AnsibleFindingPublic } from "@/client"
import { AnsibleService } from "@/client"
import { FindingRow, SubtitleDetail } from "@/components/FindingRow"
import { useFindingLifecycle } from "@/hooks/useFindingLifecycle"

export function AnsibleFindingRow({
  finding,
}: {
  finding: AnsibleFindingPublic
}) {
  const ignored = finding.status === "ignored"
  const mutation = useFindingLifecycle({
    findingId: finding.id,
    ignored,
    ignore: (ansibleFindingId) =>
      AnsibleService.ignoreFinding({ ansibleFindingId }),
    unignore: (ansibleFindingId) =>
      AnsibleService.unignoreFinding({ ansibleFindingId }),
    invalidateKeys: [["ansible-findings", finding.ansible_project_id]],
  })

  return (
    <FindingRow
      finding={finding}
      onToggleIgnore={() => mutation.mutate()}
      ignorePending={mutation.isPending}
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
