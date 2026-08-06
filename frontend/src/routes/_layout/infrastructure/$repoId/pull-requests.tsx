import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { TerraformService } from "@/client"
import { EnginePullRequestsTab } from "@/components/EnginePullRequestsTab"
import { tfFixBranch } from "@/lib/delivery"

export const Route = createFileRoute(
  "/_layout/infrastructure/$repoId/pull-requests",
)({
  component: TerraformPullRequestsTab,
  head: () => ({
    meta: [{ title: "Terraform PRs - GreenSecOps" }],
  }),
})

// Terraform PR branches carry a distinct prefix; the Infrastructure PRs tab
// only lists those, keeping CI-workflow fix PRs on the Repositories page.
const TF_BRANCH_PREFIX = "greensecops/terraform-"

function TerraformPullRequestsTab() {
  const { repoId } = Route.useParams()
  const { data: roots } = useQuery({
    queryKey: ["terraform-roots", "repo", repoId],
    queryFn: () => TerraformService.listTerraformRoots({ repoId }),
  })

  return (
    <EnginePullRequestsTab
      repoId={repoId}
      label="Terraform"
      branchPrefix={TF_BRANCH_PREFIX}
      targets={roots}
      branchForTarget={tfFixBranch}
      deliver={({ targetId, force }) =>
        TerraformService.triggerTerraformDelivery({ rootId: targetId, force })
      }
    />
  )
}
