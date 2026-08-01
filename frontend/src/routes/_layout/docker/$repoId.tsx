import { useQuery } from "@tanstack/react-query"
import {
  createFileRoute,
  Link,
  Outlet,
  useRouterState,
} from "@tanstack/react-router"
import { ArrowLeft, Lock } from "lucide-react"
import { DockerService } from "@/client"
import { GradeBadge } from "@/components/GradeBadge"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { useRepository } from "@/hooks/useRepository"
import { worstGrade } from "@/lib/grades"
import { cn } from "@/lib/utils"

export const Route = createFileRoute("/_layout/docker/$repoId")({
  component: DockerRepoLayout,
  head: () => ({
    meta: [{ title: "Docker - GreenSecOps" }],
  }),
})

const navItems = [
  { label: "Analysis", to: "analysis" },
  { label: "Runtime", to: "runtime" },
  { label: "PRs", to: "pull-requests" },
  { label: "Scan history", to: "scans" },
] as const

function DockerRepoLayout() {
  const { repoId } = Route.useParams()
  const currentPath = useRouterState({ select: (s) => s.location.pathname })
  const { repo, isLoading: repoLoading } = useRepository(repoId)

  const { data: targets } = useQuery({
    queryKey: ["docker-targets", "repo", repoId],
    queryFn: () => DockerService.listDockerTargets({ repoId }),
  })

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-3">
        <Link
          to="/docker"
          className="text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
        </Link>
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
          <GradeBadge
            grade={worstGrade((targets ?? []).map((t) => t.latest_grade))}
          />
        </div>
      </div>

      <nav className="flex gap-1 border-b overflow-x-auto scrollbar-none">
        {navItems.map((item) => {
          const href = `/docker/${repoId}/${item.to}`
          const isActive = currentPath.startsWith(href)
          return (
            <Link
              key={item.to}
              to={`/docker/$repoId/${item.to}`}
              params={{ repoId }}
              className={cn(
                "px-3 py-2 text-sm font-medium whitespace-nowrap transition-colors border-b-2 -mb-px",
                isActive
                  ? "border-foreground text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground hover:border-muted-foreground/50",
              )}
            >
              {item.label}
            </Link>
          )
        })}
      </nav>

      <Outlet />
    </div>
  )
}
