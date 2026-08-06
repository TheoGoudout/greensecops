import { createFileRoute } from "@tanstack/react-router"
import type { DockerTargetPublic } from "@/client"
import { DockerService } from "@/client"
import {
  BADGE_API_BASE,
  type BadgeEntry,
  BadgePage,
  signedBadgeUrl,
} from "@/components/BadgeGrid"

export const Route = createFileRoute("/_layout/badges/docker")({
  component: DockerBadges,
  head: () => ({
    meta: [{ title: "Docker Badges - GreenSecOps" }],
  }),
})

function toEntry(target: DockerTargetPublic): BadgeEntry {
  const svgUrl = signedBadgeUrl(
    `${BADGE_API_BASE}/api/v1/badges/docker/${target.id}.svg`,
    target.badge_sig,
  )
  // A root-path target covers the whole repo, so the repo name says it all —
  // appending "/" would just read as "acme/web-app / /".
  const repo = target.repo_full_name ?? target.repo_id
  return {
    key: target.id,
    title: target.root_path ? `${repo} / ${target.root_path}` : repo,
    svgUrl,
    markdown: `![GreenSecOps Docker](${svgUrl})`,
  }
}

function DockerBadges() {
  return (
    <BadgePage
      queryKey={["docker-targets"]}
      queryFn={() => DockerService.listDockerTargets({})}
      toEntry={toEntry}
      subject="Docker targets"
    />
  )
}
