import { createFileRoute, Outlet } from "@tanstack/react-router"
import { TabNav, type TabNavItem } from "@/components/Common/TabNav"

export const Route = createFileRoute("/_layout/badges")({
  component: BadgesLayout,
  head: () => ({
    meta: [{ title: "Badges - GreenSecOps" }],
  }),
})

// One page per engine rather than one sidebar entry per engine: a badge is the
// same artifact whichever engine graded it, and three top-level entries named
// "<Engine> Badges" put the noun last where it is hardest to scan.
const NAV: readonly TabNavItem[] = [
  { label: "Repositories", to: "/badges/repositories" },
  { label: "Terraform", to: "/badges/terraform" },
  { label: "Ansible", to: "/badges/ansible" },
  { label: "Docker", to: "/badges/docker" },
]

function BadgesLayout() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Badges</h1>
        <p className="text-muted-foreground">
          Embed GreenSecOps grade badges in your repository READMEs
        </p>
      </div>

      <TabNav items={NAV} />
      <Outlet />
    </div>
  )
}
