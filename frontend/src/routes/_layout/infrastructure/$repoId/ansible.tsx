import { createFileRoute } from "@tanstack/react-router"
import type {
  AnsibleFilePublic,
  AnsibleFindingPublic,
  AnsibleFixPublic,
  AnsibleProjectPublic,
} from "@/client"
import { AnsibleService } from "@/client"
import { AnsibleFindingRow } from "@/components/AnsibleFindingRow"
import { type FileEngine, FileTargetTab } from "@/components/FileTargetTab"
import { ansibleFixBranch } from "@/lib/delivery"

export const Route = createFileRoute("/_layout/infrastructure/$repoId/ansible")(
  {
    component: AnsibleTab,
    head: () => ({
      meta: [{ title: "Ansible - GreenSecOps" }],
    }),
  },
)

const ANSIBLE: FileEngine<
  AnsibleProjectPublic,
  AnsibleFilePublic,
  AnsibleFindingPublic,
  AnsibleFixPublic
> = {
  keyPrefix: "ansible",
  targetLabel: "Ansible project",
  noun: "project",
  label: "Ansible",
  empty: (
    <>
      <p>No Ansible projects registered for this repository.</p>
      <p className="mt-1">
        Register one from the Infrastructure page to start grading its playbooks
        and roles.
      </p>
    </>
  ),
  fixBranch: ansibleFixBranch,
  listTargets: (repoId) => AnsibleService.listProjects({ repoId }),
  calls: (projectId) => ({
    listFiles: () => AnsibleService.listFiles({ projectId }),
    listFindings: () => AnsibleService.listFindings({ projectId }),
    listFixes: () => AnsibleService.listFixes({ projectId }),
    toggle: (enabled) =>
      AnsibleService.updateProject({ projectId, requestBody: { enabled } }),
    scan: () => AnsibleService.triggerScan({ projectId }),
    remove: () => AnsibleService.deleteProject({ projectId }),
    generate: (findingIds, force) =>
      AnsibleService.generateFixes({
        projectId,
        force,
        requestBody: findingIds.length ? { finding_ids: findingIds } : {},
      }),
    deliver: (force) => AnsibleService.deliverFixes({ projectId, force }),
  }),
  listScans: (projectId) => AnsibleService.listScans({ projectId }),
  // Every kind this engine reads is YAML — playbooks, task files, variables and
  // galaxy requirements alike — so the classifier's `kind` labels the file
  // rather than picking a grammar.
  grammarOf: () => "yaml",
  kindOf: (file) => file.kind,
  renderFinding: (finding, targetState) => (
    <AnsibleFindingRow finding={finding} targetState={targetState} />
  ),
}

function AnsibleTab() {
  const { repoId } = Route.useParams()
  return <FileTargetTab engine={ANSIBLE} repoId={repoId} />
}
