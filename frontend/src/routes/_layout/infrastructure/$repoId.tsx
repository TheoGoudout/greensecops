import { createFileRoute, Outlet, useRouterState } from "@tanstack/react-router"
import { RepoPageHeader } from "@/components/Common/RepoPageHeader"
import { TabNav, type TabNavItem } from "@/components/Common/TabNav"
import { GradeBadge } from "@/components/GradeBadge"
import { useRepository } from "@/hooks/useRepository"
import { engineGrade } from "@/lib/grades"

export const Route = createFileRoute("/_layout/infrastructure/$repoId")({
  component: InfrastructureRepoLayout,
  head: () => ({
    meta: [{ title: "Infrastructure - GreenSecOps" }],
  }),
})

// Two disjoint tab sets, mirroring AppSidebar's own infraSubItems /
// ansibleSubItems split: Terraform and Ansible are different engines that
// happen to share this URL prefix, not tabs of one page, so neither list
// names the other. Cloud posture is Terraform's, not Ansible's, for the same
// reason the sidebar excludes it there.
const NAV_TERRAFORM: readonly TabNavItem[] = [
  { label: "Analysis", to: "/infrastructure/$repoId/terraform" },
  { label: "Cloud", to: "/infrastructure/$repoId/cloud" },
  { label: "PRs", to: "/infrastructure/$repoId/pull-requests" },
]

const NAV_ANSIBLE: readonly TabNavItem[] = [
  { label: "Analysis", to: "/infrastructure/$repoId/ansible" },
  { label: "PRs", to: "/infrastructure/$repoId/pull-requests" },
]

function InfrastructureRepoLayout() {
  const { repoId } = Route.useParams()
  const { repo, isLoading } = useRepository(repoId)
  const currentPath = useRouterState({ select: (s) => s.location.pathname })

  // The PRs page is shared cross-engine (see pull-requests.tsx), so it falls
  // under Terraform's tab set by default — same as AppSidebar's own
  // onAnsibleRoute check, which only lights up Ansible for its own segment.
  const onAnsible = currentPath.startsWith(`/infrastructure/${repoId}/ansible`)
  const nav = onAnsible ? NAV_ANSIBLE : NAV_TERRAFORM
  // The grade follows the tab set for the same reason the tabs do: these are
  // two engines sharing a URL prefix, not two views of one thing, and a single
  // header grade would have to be one of them. This page showed none at all.
  const onCloud = currentPath.startsWith(`/infrastructure/${repoId}/cloud`)
  const engine = onAnsible ? "ansible" : onCloud ? "cloud" : "terraform"

  return (
    <div className="flex flex-col gap-6">
      <RepoPageHeader
        backTo="/infrastructure"
        fullName={repo?.full_name}
        isLoading={isLoading}
        isPrivate={repo?.is_private}
        trailing={<GradeBadge grade={engineGrade(repo, engine)} />}
      />
      <TabNav items={nav} params={{ repoId }} />
      <Outlet />
    </div>
  )
}
