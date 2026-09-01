import { createFileRoute, Outlet } from "@tanstack/react-router"
import { RepoPageHeader } from "@/components/Common/RepoPageHeader"
import { TabNav, type TabNavItem } from "@/components/Common/TabNav"
import { GradeBadge } from "@/components/GradeBadge"
import { useRepository } from "@/hooks/useRepository"
import { engineGrade } from "@/lib/grades"

export const Route = createFileRoute("/_layout/docker/$repoId")({
  component: DockerRepoLayout,
  head: () => ({
    meta: [{ title: "Docker - GreenSecOps" }],
  }),
})

const NAV: readonly TabNavItem[] = [
  { label: "Analysis", to: "/docker/$repoId/analysis" },
  { label: "Runtime", to: "/docker/$repoId/runtime" },
  { label: "PRs", to: "/docker/$repoId/pull-requests" },
  { label: "Scan history", to: "/docker/$repoId/scans" },
]

function DockerRepoLayout() {
  const { repoId } = Route.useParams()
  const { repo, isLoading } = useRepository(repoId)

  return (
    <div className="flex flex-col gap-6">
      <RepoPageHeader
        backTo="/docker"
        fullName={repo?.full_name}
        isLoading={isLoading}
        isPrivate={repo?.is_private}
        // The Docker engine's own average, served by the repository endpoint.
        // This used to be `worstGrade` over the target list — not an average,
        // so one bad target set the header for all of them — which also meant
        // fetching every target here purely to grade them.
        trailing={<GradeBadge grade={engineGrade(repo, "docker")} />}
      />
      <TabNav items={NAV} params={{ repoId }} />
      <Outlet />
    </div>
  )
}
