import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Outlet } from "@tanstack/react-router"
import { GitBranch, WifiOff } from "lucide-react"
import { RepositoriesService } from "@/client"
import { RepoPageHeader } from "@/components/Common/RepoPageHeader"
import { TabNav, type TabNavItem } from "@/components/Common/TabNav"
import { GradeBadge } from "@/components/GradeBadge"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useRepository } from "@/hooks/useRepository"

export const Route = createFileRoute("/_layout/repositories/$repoId")({
  component: RepositoryLayout,
  validateSearch: (search: Record<string, unknown>): { branch?: string } => ({
    branch: typeof search.branch === "string" ? search.branch : undefined,
  }),
  head: () => ({
    meta: [{ title: "Repository - GreenSecOps" }],
  }),
})

const NAV: readonly TabNavItem[] = [
  {
    label: "Static analysis",
    shortLabel: "Static",
    to: "/repositories/$repoId/static-analysis",
  },
  {
    label: "Telemetry analysis",
    shortLabel: "Telemetry",
    to: "/repositories/$repoId/telemetry",
  },
  {
    label: "PRs",
    shortLabel: "PRs",
    to: "/repositories/$repoId/pull-requests",
  },
]

function RepositoryLayout() {
  const { repoId } = Route.useParams()
  const { branch } = Route.useSearch()
  const navigate = Route.useNavigate()

  const { repo, isLoading, isAccessible } = useRepository(repoId)

  const { data: branches } = useQuery({
    queryKey: ["branches", repoId],
    queryFn: () => RepositoriesService.listRepositoryBranches({ repoId }),
    enabled: !!repo,
  })

  const branchOptions = branches
    ? repo?.default_branch && !branches.includes(repo.default_branch)
      ? [repo.default_branch, ...branches]
      : branches
    : repo?.default_branch
      ? [repo.default_branch]
      : []

  return (
    <div className="flex flex-col gap-6">
      <RepoPageHeader
        backTo="/repositories"
        fullName={repo?.full_name}
        isLoading={isLoading}
        isPrivate={repo?.is_private}
        trailing={<GradeBadge grade={repo?.grade ?? null} />}
        below={
          repo && (
            <div className="flex items-center gap-1 mt-0.5">
              <GitBranch className="h-3 w-3 text-muted-foreground shrink-0" />
              <Select
                value={branch ?? repo.default_branch}
                onValueChange={(val) =>
                  navigate({
                    search: val !== repo.default_branch ? { branch: val } : {},
                  })
                }
              >
                <SelectTrigger className="h-6 text-xs border-none shadow-none px-1 gap-1 text-muted-foreground hover:text-foreground w-auto">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {branchOptions.map((b) => (
                    <SelectItem key={b} value={b} className="text-xs">
                      {b}
                      {b === repo.default_branch && (
                        <span className="ml-1 text-muted-foreground">
                          (default)
                        </span>
                      )}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )
        }
      />

      {!isLoading && !isAccessible && (
        <div className="flex items-center gap-2 rounded-md border border-orange-200 bg-orange-50 px-4 py-3 text-sm text-orange-700 dark:border-orange-900 dark:bg-orange-950/40 dark:text-orange-300">
          <WifiOff className="h-4 w-4 shrink-0" />
          <span>
            GitHub App access lost — this repository is disabled. Actions are
            unavailable until access is restored.
          </span>
        </div>
      )}

      <TabNav
        items={NAV}
        params={{ repoId }}
        search={branch ? { branch } : {}}
      />
      <Outlet />
    </div>
  )
}
