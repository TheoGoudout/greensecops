import { createFileRoute } from "@tanstack/react-router"
import type { CloudAccountPublic } from "@/client"
import { CloudService } from "@/client"
import {
  BADGE_API_BASE,
  type BadgeEntry,
  BadgePage,
  signedBadgeUrl,
} from "@/components/BadgeGrid"

export const Route = createFileRoute("/_layout/badges/cloud")({
  component: CloudBadges,
  head: () => ({
    meta: [{ title: "Cloud Badges - GreenSecOps" }],
  }),
})

function toEntry(account: CloudAccountPublic): BadgeEntry {
  const svgUrl = signedBadgeUrl(
    `${BADGE_API_BASE}/api/v1/badges/cloud-accounts/${account.id}.svg`,
    account.badge_sig,
  )
  return {
    key: account.id,
    title: account.display_name,
    svgUrl,
    markdown: `![GreenSecOps Cloud](${svgUrl})`,
  }
}

function CloudBadges() {
  return (
    <BadgePage
      queryKey={["cloud-accounts"]}
      queryFn={() => CloudService.listAccounts({})}
      toEntry={toEntry}
      subject="Cloud accounts"
    />
  )
}
