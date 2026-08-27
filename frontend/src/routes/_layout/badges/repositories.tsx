import { createFileRoute } from "@tanstack/react-router"
import type { RepositoryPublic } from "@/client"
import { RepositoriesService } from "@/client"
import {
  BADGE_API_BASE,
  type BadgeEntry,
  BadgePage,
  signedBadgeUrl,
} from "@/components/BadgeGrid"

export const Route = createFileRoute("/_layout/badges/repositories")({
  component: RepositoryBadges,
  head: () => ({
    meta: [{ title: "Badges - GreenSecOps" }],
  }),
})

function toEntry(repo: RepositoryPublic): BadgeEntry {
  const [owner, name] = repo.full_name.split("/")
  const svgUrl = signedBadgeUrl(
    `${BADGE_API_BASE}/api/v1/badges/repositories/${owner}/${name}/${repo.default_branch}.svg`,
    repo.badge_sig,
  )
  return {
    key: repo.id,
    title: repo.full_name,
    svgUrl,
    markdown: `![GreenSecOps](${svgUrl})`,
  }
}

function RepositoryBadges() {
  return (
    <BadgePage
      queryKey={["repositories"]}
      queryFn={() => RepositoriesService.listRepositories({ limit: 200 })}
      toEntry={toEntry}
      subject="repositories"
    />
  )
}
