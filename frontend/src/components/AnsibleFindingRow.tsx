import type { AnsibleFindingPublic } from "@/client"
import { AnsibleService } from "@/client"
import { FindingRow, SubtitleDetail } from "@/components/FindingRow"
import { useFindingLifecycle } from "@/hooks/useFindingLifecycle"
import { type EngineActionInput, ignoreAction } from "@/lib/engine-actions"

export function AnsibleFindingRow({
  finding,
  targetState,
}: {
  finding: AnsibleFindingPublic
  /** What the owning target is doing, from the page's own action input. A
   * running scan is about to replace this finding, so muting it is refused. */
  targetState: EngineActionInput
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
      ignore={ignoreAction(finding.status, {
        ...targetState,
        pending: { ignore: mutation.isPending },
      })}
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
