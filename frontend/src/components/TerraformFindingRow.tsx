import type { TerraformFindingPublic } from "@/client"
import { TerraformService } from "@/client"
import { FindingRow, SubtitleDetail } from "@/components/FindingRow"
import { useFindingLifecycle } from "@/hooks/useFindingLifecycle"
import { type EngineActionInput, ignoreAction } from "@/lib/engine-actions"

export function TerraformFindingRow({
  finding,
  targetState,
}: {
  finding: TerraformFindingPublic
  /** What the owning target is doing, from the page's own action input. A
   * running scan is about to replace this finding, so muting it is refused. */
  targetState: EngineActionInput
}) {
  const ignored = finding.status === "ignored"
  const mutation = useFindingLifecycle({
    findingId: finding.id,
    ignored,
    ignore: (terraformFindingId) =>
      TerraformService.ignoreFinding({ terraformFindingId }),
    unignore: (terraformFindingId) =>
      TerraformService.unignoreFinding({ terraformFindingId }),
    invalidateKeys: [["terraform-findings", finding.terraform_root_id]],
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
          {finding.resource_address ?? finding.file_path}
          {finding.line_start && (
            <SubtitleDetail>L{finding.line_start}</SubtitleDetail>
          )}
        </>
      }
    />
  )
}
