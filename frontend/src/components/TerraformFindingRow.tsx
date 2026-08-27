import type { TerraformFindingPublic } from "@/client"
import { TerraformService } from "@/client"
import { FindingRow, SubtitleDetail } from "@/components/FindingRow"
import { useFindingLifecycle } from "@/hooks/useFindingLifecycle"

export function TerraformFindingRow({
  finding,
}: {
  finding: TerraformFindingPublic
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
      ignorePending={mutation.isPending}
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
