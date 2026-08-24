import { Link, useRouterState } from "@tanstack/react-router"
import { cn } from "@/lib/utils"

export interface TabNavItem {
  /** Router target, e.g. `/docker/$repoId/analysis` or `/badges/docker`. */
  to: string
  label: string
  /** Shown below the `sm` breakpoint. Falls back to `label`. */
  shortLabel?: string
}

/**
 * The underlined tab strip used by every section that has sub-pages.
 *
 * This markup existed four times — in the repository, Docker and infrastructure
 * layouts and on the badges page — as a byte-identical copy of the same `<nav>`,
 * including the two long Tailwind strings that decide what an active tab looks
 * like. Changing the active colour meant finding all four.
 *
 * A tab is active when the current path starts with its resolved target, so a
 * nested route (`/docker/x/analysis/detail`) keeps its parent tab lit.
 */
export function TabNav({
  items,
  params,
  search,
}: {
  items: readonly TabNavItem[]
  /** Path params to fill into each `to`, e.g. `{ repoId }`. */
  params?: Record<string, string>
  /** Search params carried across tab switches, e.g. the selected branch. */
  search?: Record<string, unknown>
}) {
  const currentPath = useRouterState({ select: (s) => s.location.pathname })

  return (
    <nav className="flex gap-1 border-b overflow-x-auto scrollbar-none">
      {items.map((item) => {
        // The concrete URL, for matching: `/docker/$repoId/analysis` with
        // `{repoId: "abc"}` is active on `/docker/abc/analysis`.
        const href = params
          ? item.to.replace(/\$(\w+)/g, (whole, key) => params[key] ?? whole)
          : item.to
        const isActive = currentPath.startsWith(href)
        return (
          <Link
            key={item.to}
            to={item.to}
            params={params}
            search={search}
            className={cn(
              "px-3 py-2 text-sm font-medium whitespace-nowrap transition-colors border-b-2 -mb-px",
              isActive
                ? "border-foreground text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground hover:border-muted-foreground/50",
            )}
          >
            {item.shortLabel ? (
              <>
                <span className="sm:hidden">{item.shortLabel}</span>
                <span className="hidden sm:inline">{item.label}</span>
              </>
            ) : (
              item.label
            )}
          </Link>
        )
      })}
    </nav>
  )
}
