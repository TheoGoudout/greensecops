import { createFileRoute } from "@tanstack/react-router"
import type {
  TerraformFilePublic,
  TerraformFindingPublic,
  TerraformFixPublic,
  TerraformRootPublic,
} from "@/client"
import { TerraformService } from "@/client"
import { type FileEngine, FileTargetTab } from "@/components/FileTargetTab"
import { TerraformFindingRow } from "@/components/TerraformFindingRow"
import { tfFixBranch } from "@/lib/delivery"

export const Route = createFileRoute(
  "/_layout/infrastructure/$repoId/terraform",
)({
  component: TerraformTab,
  head: () => ({
    meta: [{ title: "Terraform - GreenSecOps" }],
  }),
})

const TERRAFORM: FileEngine<
  TerraformRootPublic,
  TerraformFilePublic,
  TerraformFindingPublic,
  TerraformFixPublic
> = {
  keyPrefix: "terraform",
  targetLabel: "Terraform root",
  noun: "root",
  label: "Terraform",
  empty: (
    <>
      No Terraform roots configured for this repository. Add one from the{" "}
      <span className="font-medium">Infrastructure</span> list.
    </>
  ),
  fixBranch: tfFixBranch,
  listTargets: (repoId) => TerraformService.listRoots({ repoId }),
  calls: (rootId) => ({
    listFiles: () => TerraformService.listFiles({ rootId }),
    listFindings: () => TerraformService.listFindings({ rootId }),
    listFixes: () => TerraformService.listFixes({ rootId }),
    toggle: (enabled) =>
      TerraformService.updateRoot({ rootId, requestBody: { enabled } }),
    scan: () => TerraformService.triggerScan({ rootId }),
    remove: () => TerraformService.deleteRoot({ rootId }),
    generate: (findingIds, force) =>
      TerraformService.generateFixes({
        rootId,
        force,
        requestBody: findingIds.length ? { finding_ids: findingIds } : {},
      }),
    deliver: (force) => TerraformService.deliverFixes({ rootId, force }),
  }),
  listScans: (rootId) => TerraformService.listScans({ rootId }),
  grammarOf: () => "hcl",
  renderFinding: (finding, targetState) => (
    <TerraformFindingRow finding={finding} targetState={targetState} />
  ),
}

function TerraformTab() {
  const { repoId } = Route.useParams()
  return <FileTargetTab engine={TERRAFORM} repoId={repoId} />
}
