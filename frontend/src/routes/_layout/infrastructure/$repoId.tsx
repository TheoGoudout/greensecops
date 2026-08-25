import { createFileRoute, Outlet } from "@tanstack/react-router"
import { RepoPageHeader } from "@/components/Common/RepoPageHeader"
import { TabNav, type TabNavItem } from "@/components/Common/TabNav"
import { useRepository } from "@/hooks/useRepository"

export const Route = createFileRoute("/_layout/infrastructure/$repoId")({
  component: InfrastructureRepoLayout,
  head: () => ({
    meta: [{ title: "Infrastructure - GreenSecOps" }],
  }),
})

const NAV: readonly TabNavItem[] = [
  { label: "Analysis", to: "/infrastructure/$repoId/terraform" },
  { label: "Cloud", to: "/infrastructure/$repoId/cloud" },
  { label: "PRs", to: "/infrastructure/$repoId/pull-requests" },
]

function InfrastructureRepoLayout() {
  const { repoId } = Route.useParams()
  const { repo, isLoading } = useRepository(repoId)

  return (
    <div className="flex flex-col gap-6">
      <RepoPageHeader
        backTo="/infrastructure"
        fullName={repo?.full_name}
        isLoading={isLoading}
        isPrivate={repo?.is_private}
      />
      <TabNav items={NAV} params={{ repoId }} />
      <Outlet />
    </div>
  )
}
