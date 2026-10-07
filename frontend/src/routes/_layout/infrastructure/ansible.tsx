import { createFileRoute } from "@tanstack/react-router"
import { ScrollText } from "lucide-react"
import type { AnsibleProjectPublic } from "@/client"
import { AnsibleService } from "@/client"
import { type TargetList, TargetListPage } from "@/components/TargetListPage"

// A static sibling of `$repoId`, the same way `badges` is: the router prefers
// the literal segment, and `AppSidebar` excludes both names when it reads a
// repo id out of the path.
export const Route = createFileRoute("/_layout/infrastructure/ansible")({
  component: AnsibleIndexPage,
  head: () => ({
    meta: [{ title: "Ansible - GreenSecOps" }],
  }),
})

const ANSIBLE_PROJECTS: TargetList<AnsibleProjectPublic> = {
  keyPrefix: "ansible",
  title: "Ansible",
  description: "Playbooks, roles and fixes, per repository.",
  noun: "project",
  pluralLabel: "Ansible projects",
  targetLabel: "Ansible project",
  icon: ScrollText,
  placeholder: "deploy/ansible (blank = repository root)",
  allowRepoRoot: true,
  empty: (
    <>
      No Ansible projects configured. Pick a repository and add the folder
      holding your playbooks and roles (e.g.{" "}
      <code className="font-mono">deploy/ansible</code>), or leave the path
      blank if they live at the repository root.
    </>
  ),
  repoLink: "/infrastructure/$repoId/ansible",
  listTargets: () => AnsibleService.listProjects({}),
  createTarget: (repoId, rootPath) =>
    AnsibleService.createProject({
      requestBody: { repo_id: repoId, root_path: rootPath },
    }),
}

function AnsibleIndexPage() {
  return <TargetListPage list={ANSIBLE_PROJECTS} />
}
