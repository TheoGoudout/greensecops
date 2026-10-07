import { createFileRoute } from "@tanstack/react-router"
import type {
  DockerFilePublic,
  DockerFindingPublic,
  DockerFixPublic,
  DockerTargetPublic,
} from "@/client"
import { DockerService } from "@/client"
import { DockerFindingRow } from "@/components/DockerFindingRow"
import { type FileEngine, FileTargetTab } from "@/components/FileTargetTab"
import { dockerFixBranch } from "@/lib/delivery"

export const Route = createFileRoute("/_layout/docker/$repoId/analysis")({
  component: DockerAnalysisTab,
  head: () => ({
    meta: [{ title: "Docker analysis - GreenSecOps" }],
  }),
})

const DOCKER: FileEngine<
  DockerTargetPublic,
  DockerFilePublic,
  DockerFindingPublic,
  DockerFixPublic
> = {
  keyPrefix: "docker",
  targetLabel: "Docker target",
  noun: "target",
  label: "Docker",
  empty:
    "No Docker targets yet. One is created automatically when the GitHub App syncs this repository.",
  fixBranch: dockerFixBranch,
  listTargets: (repoId) => DockerService.listTargets({ repoId }),
  calls: (targetId) => ({
    listFiles: () => DockerService.listFiles({ targetId }),
    listFindings: () => DockerService.listFindings({ targetId }),
    listFixes: () => DockerService.listFixes({ targetId }),
    toggle: (enabled) =>
      DockerService.updateTarget({ targetId, requestBody: { enabled } }),
    scan: () => DockerService.triggerScan({ targetId }),
    remove: () => DockerService.deleteTarget({ targetId }),
    generate: (findingIds, force) =>
      DockerService.generateFixes({
        targetId,
        force,
        requestBody: findingIds.length ? { finding_ids: findingIds } : {},
      }),
    deliver: (force) => DockerService.deliverFixes({ targetId, force }),
  }),
  // No `listScans`: Docker shows its scans on a tab of their own.
  // The API reports the kind, so the grammar is never re-derived from the
  // filename here.
  grammarOf: (file) => (file.kind === "compose" ? "compose" : "dockerfile"),
  renderFinding: (finding, targetState) => (
    <DockerFindingRow finding={finding} targetState={targetState} />
  ),
}

function DockerAnalysisTab() {
  const { repoId } = Route.useParams()
  return <FileTargetTab engine={DOCKER} repoId={repoId} />
}
