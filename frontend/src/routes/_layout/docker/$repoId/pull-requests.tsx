import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { DockerService } from "@/client"
import { EnginePullRequestsTab } from "@/components/EnginePullRequestsTab"
import { dockerFixBranch } from "@/lib/delivery"

export const Route = createFileRoute("/_layout/docker/$repoId/pull-requests")({
  component: DockerPullRequestsTab,
  head: () => ({
    meta: [{ title: "Docker PRs - GreenSecOps" }],
  }),
})

// Docker PR branches carry a distinct prefix; this tab only lists those,
// keeping Terraform and CI-workflow fix PRs on their own pages.
const DOCKER_BRANCH_PREFIX = "greensecops/docker-"

function DockerPullRequestsTab() {
  const { repoId } = Route.useParams()
  const { data: targets } = useQuery({
    queryKey: ["docker-targets", "repo", repoId],
    queryFn: () => DockerService.listTargets({ repoId }),
  })

  return (
    <EnginePullRequestsTab
      repoId={repoId}
      label="Docker"
      branchPrefix={DOCKER_BRANCH_PREFIX}
      targets={targets}
      branchForTarget={dockerFixBranch}
      deliver={({ targetId, force }) =>
        DockerService.deliverFixes({ targetId, force })
      }
    />
  )
}
