import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { useMemo } from "react"
import type { TerraformRootPublic } from "@/client"
import { TerraformService } from "@/client"
import {
  BADGE_API_BASE,
  type BadgeEntry,
  BadgeGrid,
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
    `${BADGE_API_BASE}/api/v1/badges/terraform/${root.id}.svg`,
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
  const {
    data: roots,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["terraform-roots"],
    queryFn: () => TerraformService.listTerraformRoots({}),
  })

  const entries = useMemo(() => (roots ?? []).map(toEntry), [roots])

  return (
    <BadgeGrid
      entries={entries}
      isLoading={isLoading}
      isError={isError}
      errorLabel="Failed to load Terraform roots."
      emptyLabel="No Terraform roots found."
    />
  )
}
