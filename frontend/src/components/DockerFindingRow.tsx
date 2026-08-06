import type { DockerFindingPublic } from "@/client"
import { FindingRow, SubtitleDetail } from "@/components/FindingRow"

export function DockerFindingRow({
  finding,
}: {
  finding: DockerFindingPublic
}) {
  // A Compose rule names the service it fired on, a Dockerfile rule the build
  // stage; a file-level rule (a missing OCI label) names neither and falls
  // back to the path alone.
  const locator = finding.service_name ?? finding.stage_name

  return (
    <FindingRow
      finding={finding}
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
