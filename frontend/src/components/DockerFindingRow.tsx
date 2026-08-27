import type { DockerFindingPublic } from "@/client"
import { DockerService } from "@/client"
import { FindingRow, SubtitleDetail } from "@/components/FindingRow"
import { useFindingLifecycle } from "@/hooks/useFindingLifecycle"

export function DockerFindingRow({
  finding,
}: {
  finding: DockerFindingPublic
}) {
  // A Compose rule names the service it fired on, a Dockerfile rule the build
  // stage; a file-level rule (a missing OCI label) names neither and falls
  // back to the path alone.
  const locator = finding.service_name ?? finding.stage_name
  const ignored = finding.status === "ignored"
  const mutation = useFindingLifecycle({
    findingId: finding.id,
    ignored,
    ignore: (dockerFindingId) =>
      DockerService.ignoreFinding({ dockerFindingId }),
    unignore: (dockerFindingId) =>
      DockerService.unignoreFinding({ dockerFindingId }),
    invalidateKeys: [["docker-findings", finding.docker_target_id]],
  })

  return (
    <FindingRow
      finding={finding}
      onToggleIgnore={() => mutation.mutate()}
      ignorePending={mutation.isPending}
      subtitle={
        <>
          {finding.file_path}
          {locator && <SubtitleDetail>{locator}</SubtitleDetail>}
          {finding.line_start && (
            <SubtitleDetail>L{finding.line_start}</SubtitleDetail>
          )}
        </>
      }
    />
  )
}
