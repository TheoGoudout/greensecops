import { useMutation, useQuery } from "@tanstack/react-query"
import {
  createFileRoute,
  Link,
  Outlet,
  useRouterState,
} from "@tanstack/react-router"
import { ArrowLeft, GitBranch, Play, Puzzle } from "lucide-react"
import { toast } from "sonner"
import { AnalysesService, ApiError, RepositoriesService } from "@/client"
import { GradeBadge } from "@/components/GradeBadge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

export const Route = createFileRoute("/_layout/repositories/$repoId")({
  component: RepositoryLayout,
  head: () => ({
    meta: [{ title: "Repository - GreenSecOps" }],
  }),
})

const navItems = [
  { label: "Analyses", shortLabel: "Analyses", to: "analyses" },
  { label: "Issues", shortLabel: "Issues", to: "issues" },
  { label: "Workflow", shortLabel: "Workflow", to: "workflow" },
  { label: "Fixes", shortLabel: "Fixes", to: "fixes" },
  { label: "Pull Requests", shortLabel: "PRs", to: "pull-requests" },
] as const

function RepositoryLayout() {
  const { repoId } = Route.useParams()
  const currentPath = useRouterState({
    select: (s) => s.location.pathname,
  })

  const { data: repo, isLoading: repoLoading } = useQuery({
    queryKey: ["repository", repoId],
    queryFn: () => RepositoriesService.getRepository({ repoId }),
  })

  const currentGrade = repo?.grade ?? null

  const triggerMutation = useMutation({
    mutationFn: () => AnalysesService.triggerAnalysis({ repoId }),
    onSuccess: () => toast.success("Analysis queued"),
    onError: () => toast.error("Failed to trigger analysis"),
  })

  const integrateActionMutation = useMutation({
    mutationFn: () => RepositoriesService.integrateAction({ repoId }),
    onSuccess: (data) => {
      toast.success("PR opened", {
        description: data.pr_url,
        action: data.pr_url
          ? {
              label: "Open",
              onClick: () => window.open(data.pr_url, "_blank"),
            }
          : undefined,
      })
    },
    onError: (error) => {
      const detail =
        error instanceof ApiError
          ? (error.body as { detail?: string })?.detail
          : undefined
      toast.error("Failed to integrate action", {
        description: detail,
      })
    },
  })

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
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
              <GradeBadge grade={currentGrade} />
            </div>
            {repo && (
              <span className="inline-flex items-center gap-1 text-xs text-muted-foreground mt-0.5">
                <GitBranch className="h-3 w-3" />
                default: {repo.default_branch}
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            className="gap-2"
            onClick={() => integrateActionMutation.mutate()}
            disabled={
              integrateActionMutation.isPending ||
              integrateActionMutation.isSuccess
            }
          >
            <Puzzle className="h-4 w-4" />
            {integrateActionMutation.isPending
              ? "Opening PR…"
              : integrateActionMutation.isSuccess
                ? "PR opened"
                : "Integrate action"}
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="gap-2"
            onClick={() => triggerMutation.mutate()}
            disabled={triggerMutation.isPending}
          >
            <Play className="h-4 w-4" />
            Run analysis
          </Button>
        </div>
      </div>

      <nav className="flex gap-1 border-b overflow-x-auto scrollbar-none">
        {navItems.map((item) => {
          const href = `/repositories/${repoId}/${item.to}`
          const isActive = currentPath.startsWith(href)
          return (
            <Link
              key={item.to}
              to={`/repositories/$repoId/${item.to}`}
              params={{ repoId }}
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
