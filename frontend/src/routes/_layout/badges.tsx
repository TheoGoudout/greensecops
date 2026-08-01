import {
  createFileRoute,
  Link,
  Outlet,
  useRouterState,
} from "@tanstack/react-router"
import { cn } from "@/lib/utils"

export const Route = createFileRoute("/_layout/badges")({
  component: BadgesLayout,
  head: () => ({
    meta: [{ title: "Badges - GreenSecOps" }],
  }),
})

// One page per engine rather than one sidebar entry per engine: a badge is the
// same artifact whichever engine graded it, and three top-level entries named
// "<Engine> Badges" put the noun last where it is hardest to scan.
const navItems = [
  { label: "Repositories", to: "/badges/repositories" },
  { label: "Terraform", to: "/badges/terraform" },
  { label: "Docker", to: "/badges/docker" },
] as const

function BadgesLayout() {
  const currentPath = useRouterState({ select: (s) => s.location.pathname })

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Badges</h1>
        <p className="text-muted-foreground">
          Embed GreenSecOps grade badges in your repository READMEs
        </p>
      </div>

      <nav className="flex gap-1 border-b overflow-x-auto scrollbar-none">
        {navItems.map((item) => {
          const isActive = currentPath.startsWith(item.to)
          return (
            <Link
              key={item.to}
              to={item.to}
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
