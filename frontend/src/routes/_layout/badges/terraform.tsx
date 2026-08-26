import { createFileRoute } from "@tanstack/react-router"
import type { TerraformRootPublic } from "@/client"
import { TerraformService } from "@/client"
import {
  BADGE_API_BASE,
  type BadgeEntry,
  BadgePage,
  signedBadgeUrl,
} from "@/components/BadgeGrid"

export const Route = createFileRoute("/_layout/badges/terraform")({
  component: TerraformBadges,
  head: () => ({
    meta: [{ title: "Terraform Badges - GreenSecOps" }],
  }),
})

function toEntry(root: TerraformRootPublic): BadgeEntry {
  const svgUrl = signedBadgeUrl(
    `${BADGE_API_BASE}/api/v1/badges/terraform-roots/${root.id}.svg`,
    root.badge_sig,
  )
  return {
    key: root.id,
    // A Terraform root always has a path — it is registered by hand, never
    // defaulted to the repository root the way a Docker target is.
    title: root.repo_full_name
      ? `${root.repo_full_name} / ${root.root_path}`
      : root.root_path,
    svgUrl,
    markdown: `![GreenSecOps Terraform](${svgUrl})`,
  }
}

function TerraformBadges() {
  return (
    <BadgePage
      queryKey={["terraform-roots"]}
      queryFn={() => TerraformService.listRoots({})}
      toEntry={toEntry}
      subject="Terraform roots"
    />
  )
}
