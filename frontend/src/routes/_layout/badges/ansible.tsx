import { createFileRoute } from "@tanstack/react-router"
import type { AnsibleProjectPublic } from "@/client"
import { AnsibleService } from "@/client"
import {
  BADGE_API_BASE,
  type BadgeEntry,
  BadgePage,
  signedBadgeUrl,
} from "@/components/BadgeGrid"

export const Route = createFileRoute("/_layout/badges/ansible")({
  component: AnsibleBadges,
  head: () => ({
    meta: [{ title: "Ansible Badges - GreenSecOps" }],
  }),
})

function toEntry(project: AnsibleProjectPublic): BadgeEntry {
  const svgUrl = signedBadgeUrl(
    `${BADGE_API_BASE}/api/v1/badges/ansible/${project.id}.svg`,
    project.badge_sig,
  )
  // A project rooted at the repository root has an empty path; "/" reads
  // better than a title that trails off after the repository name.
  const path = project.root_path || "/"
  return {
    key: project.id,
    title: project.repo_full_name
      ? `${project.repo_full_name} / ${path}`
      : path,
    svgUrl,
    markdown: `![GreenSecOps Ansible](${svgUrl})`,
  }
}

function AnsibleBadges() {
  return (
    <BadgePage
      queryKey={["ansible-projects"]}
      queryFn={() => AnsibleService.listProjects({})}
      toEntry={toEntry}
      subject="Ansible projects"
    />
  )
}
