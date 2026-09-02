import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { type DockerFixPublic, DockerService } from "@/client"
import { EnginePullRequestsTab } from "@/components/EnginePullRequestsTab"
import { useRepository } from "@/hooks/useRepository"
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
  const { isAccessible } = useRepository(repoId)
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
      isAccessible={isAccessible}
      keyPrefix="docker"
      listFixes={() => DockerService.listRepositoryFixes({ repoId })}
      targetIdOfFix={(fix) => (fix as DockerFixPublic).docker_target_id}
      deliver={({ targetId, force }) =>
        DockerService.deliverFixes({ targetId, force })
      }
    />
  )
}
