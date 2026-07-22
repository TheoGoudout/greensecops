import { useQuery } from "@tanstack/react-query"
import {
  createFileRoute,
  Link,
  Outlet,
  useRouterState,
} from "@tanstack/react-router"
import { ArrowLeft, GitBranch, Lock, WifiOff } from "lucide-react"
import { RepositoriesService } from "@/client"
import { GradeBadge } from "@/components/GradeBadge"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { useRepository } from "@/hooks/useRepository"
import { cn } from "@/lib/utils"

export const Route = createFileRoute("/_layout/repositories/$repoId")({
  component: RepositoryLayout,
  validateSearch: (search: Record<string, unknown>): { branch?: string } => ({
    branch: typeof search.branch === "string" ? search.branch : undefined,
  }),
  head: () => ({
    meta: [{ title: "Repository - GreenSecOps" }],
  }),
})

const navItems = [
  { label: "Static analysis", shortLabel: "Static", to: "static-analysis" },
  { label: "Telemetry analysis", shortLabel: "Telemetry", to: "telemetry" },
  { label: "PRs", shortLabel: "PRs", to: "pull-requests" },
] as const

function RepositoryLayout() {
  const { repoId } = Route.useParams()
  const { branch } = Route.useSearch()
  const navigate = Route.useNavigate()
  const currentPath = useRouterState({
    select: (s) => s.location.pathname,
  })

  const { repo, isLoading: repoLoading, isAccessible } = useRepository(repoId)

  const { data: branches } = useQuery({
    queryKey: ["branches", repoId],
    queryFn: () => RepositoriesService.listRepositoryBranches({ repoId }),
    enabled: !!repo,
  })

  const currentGrade = repo?.grade ?? null

  const branchOptions = branches
    ? repo?.default_branch && !branches.includes(repo.default_branch)
      ? [repo.default_branch, ...branches]
      : branches
    : repo?.default_branch
      ? [repo.default_branch]
      : []

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-3">
          <Link
            to="/repositories"
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <div>
            <div className="flex items-center gap-3">
              {repoLoading ? (
                <Skeleton className="h-7 w-64" />
              ) : (
                <h1 className="text-2xl font-bold tracking-tight font-mono">
                  {repo?.full_name}
                </h1>
              )}
              {repo?.is_private && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Lock
                      aria-label="Private repository"
                      className="h-4 w-4 shrink-0 text-muted-foreground"
                    />
                  </TooltipTrigger>
                  <TooltipContent>Private repository</TooltipContent>
                </Tooltip>
              )}
              <GradeBadge grade={currentGrade} />
            </div>
            {repo && (
              <div className="flex items-center gap-1 mt-0.5">
                <GitBranch className="h-3 w-3 text-muted-foreground shrink-0" />
                <Select
                  value={branch ?? repo.default_branch}
                  onValueChange={(val) =>
                    navigate({
                      search:
                        val !== repo.default_branch ? { branch: val } : {},
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
            )}
          </div>
        </div>
      </div>

      {!repoLoading && !isAccessible && (
        <div className="flex items-center gap-2 rounded-md border border-orange-200 bg-orange-50 px-4 py-3 text-sm text-orange-700 dark:border-orange-900 dark:bg-orange-950/40 dark:text-orange-300">
          <WifiOff className="h-4 w-4 shrink-0" />
          <span>
            GitHub App access lost — this repository is disabled. Actions are
            unavailable until access is restored.
          </span>
        </div>
      )}

      <nav className="flex gap-1 border-b overflow-x-auto scrollbar-none">
        {navItems.map((item) => {
          const href = `/repositories/${repoId}/${item.to}`
          const isActive = currentPath.startsWith(href)
          return (
            <Link
              key={item.to}
              to={`/repositories/$repoId/${item.to}`}
              params={{ repoId }}
              search={branch ? { branch } : {}}
              className={cn(
                "px-3 py-2 text-sm font-medium whitespace-nowrap transition-colors border-b-2 -mb-px",
                isActive
                  ? "border-foreground text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground hover:border-muted-foreground/50",
              )}
            >
              <span className="sm:hidden">{item.shortLabel}</span>
              <span className="hidden sm:inline">{item.label}</span>
            </Link>
          )
        })}
      </nav>

      <Outlet />
    </div>
  )
}
