import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Outlet } from "@tanstack/react-router"
import { DockerService } from "@/client"
import { RepoPageHeader } from "@/components/Common/RepoPageHeader"
import { TabNav, type TabNavItem } from "@/components/Common/TabNav"
import { GradeBadge } from "@/components/GradeBadge"
import { useRepository } from "@/hooks/useRepository"
import { worstGrade } from "@/lib/grades"

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

  const { data: targets } = useQuery({
    queryKey: ["docker-targets", "repo", repoId],
    queryFn: () => DockerService.listTargets({ repoId }),
  })

  return (
    <div className="flex flex-col gap-6">
      <RepoPageHeader
        backTo="/docker"
        fullName={repo?.full_name}
        isLoading={isLoading}
        isPrivate={repo?.is_private}
        trailing={
          <GradeBadge
            grade={worstGrade((targets ?? []).map((t) => t.latest_grade))}
          />
        }
      />
      <TabNav items={NAV} params={{ repoId }} />
      <Outlet />
    </div>
  )
}
