import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import {
  type AnsibleFixPublic,
  AnsibleService,
  type TerraformFixPublic,
  TerraformService,
} from "@/client"
import { EnginePullRequestsTab } from "@/components/EnginePullRequestsTab"
import { useRepository } from "@/hooks/useRepository"
import { ansibleFixBranch, tfFixBranch } from "@/lib/delivery"

export const Route = createFileRoute(
  "/_layout/infrastructure/$repoId/pull-requests",
)({
  component: InfrastructurePullRequestsTab,
  head: () => ({
    meta: [{ title: "Infrastructure PRs - GreenSecOps" }],
  }),
})

// Each engine's PR branches carry a distinct prefix; the Infrastructure PRs tab
// lists only those, keeping CI-workflow fix PRs on the Repositories page.
const TF_BRANCH_PREFIX = "greensecops/terraform-"
const ANSIBLE_BRANCH_PREFIX = "greensecops/ansible-"

/**
 * Both Infrastructure engines' delivery PRs, one section each.
 *
 * Stacked rather than merged into one list: the two engines deliver against
 * different targets (a Terraform root, an Ansible project) and "Update PR"
 * has to call the right engine's endpoint, so a combined list would need a
 * per-row engine discriminator to do anything useful with a row.
 */
function InfrastructurePullRequestsTab() {
  const { repoId } = Route.useParams()
  const { isAccessible } = useRepository(repoId)

  const { data: roots } = useQuery({
    queryKey: ["terraform-roots", "repo", repoId],
    queryFn: () => TerraformService.listRoots({ repoId }),
  })

  const { data: projects } = useQuery({
    queryKey: ["ansible-projects", "repo", repoId],
    queryFn: () => AnsibleService.listProjects({ repoId }),
  })

  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-medium text-muted-foreground">Terraform</h2>
        <EnginePullRequestsTab
          repoId={repoId}
          label="Terraform"
          branchPrefix={TF_BRANCH_PREFIX}
          targets={roots}
          branchForTarget={tfFixBranch}
          isAccessible={isAccessible}
          keyPrefix="terraform"
          listFixes={() => TerraformService.listRepositoryFixes({ repoId })}
          targetIdOfFix={(fix) => (fix as TerraformFixPublic).terraform_root_id}
          deliver={({ targetId, force }) =>
            TerraformService.deliverFixes({ rootId: targetId, force })
          }
        />
      </section>

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-medium text-muted-foreground">Ansible</h2>
        <EnginePullRequestsTab
          repoId={repoId}
          label="Ansible"
          branchPrefix={ANSIBLE_BRANCH_PREFIX}
          targets={projects}
          branchForTarget={ansibleFixBranch}
          isAccessible={isAccessible}
          keyPrefix="ansible"
          listFixes={() => AnsibleService.listRepositoryFixes({ repoId })}
          targetIdOfFix={(fix) => (fix as AnsibleFixPublic).ansible_project_id}
          sourceTabLabel="Ansible"
          deliver={({ targetId, force }) =>
            AnsibleService.deliverFixes({
              projectId: targetId,
              force,
            })
          }
        />
      </section>
    </div>
  )
}
