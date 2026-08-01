import {
  createFileRoute,
  Link,
  Outlet,
  useRouterState,
} from "@tanstack/react-router"
import { ArrowLeft, Lock } from "lucide-react"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { useRepository } from "@/hooks/useRepository"
import { cn } from "@/lib/utils"

export const Route = createFileRoute("/_layout/infrastructure/$repoId")({
  component: InfrastructureRepoLayout,
  head: () => ({
    meta: [{ title: "Infrastructure - GreenSecOps" }],
  }),
})

const navItems = [
  { label: "Analysis", to: "terraform" },
  { label: "Cloud", to: "cloud" },
  { label: "PRs", to: "pull-requests" },
] as const

function InfrastructureRepoLayout() {
  const { repoId } = Route.useParams()
  const currentPath = useRouterState({ select: (s) => s.location.pathname })
  const { repo, isLoading: repoLoading } = useRepository(repoId)

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-3">
        <Link
          to="/infrastructure"
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
        </div>
      </div>

      <nav className="flex gap-1 border-b overflow-x-auto scrollbar-none">
        {navItems.map((item) => {
          const href = `/infrastructure/${repoId}/${item.to}`
          const isActive = currentPath.startsWith(href)
          return (
            <Link
              key={item.to}
              to={`/infrastructure/$repoId/${item.to}`}
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
