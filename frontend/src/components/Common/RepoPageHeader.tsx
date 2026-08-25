import { Link } from "@tanstack/react-router"
import { ArrowLeft, Lock } from "lucide-react"
import type { ReactNode } from "react"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

/**
 * The heading every per-repository page opens with: a back arrow, the
 * repository's name, a lock when it is private, and whatever the engine wants
 * beside it.
 *
 * Was copied into the repository, Docker and infrastructure layouts, where it
 * had already drifted — the same lock tooltip written three times is three
 * chances to give it a different `aria-label`.
 */
export function RepoPageHeader({
  backTo,
  fullName,
  isLoading,
  isPrivate,
  trailing,
  below,
}: {
  /** Where the back arrow goes — the list this repository was opened from. */
  backTo: string
  fullName: string | undefined
  isLoading: boolean
  isPrivate: boolean | null | undefined
  /** Rendered next to the name, e.g. a grade badge. */
  trailing?: ReactNode
  /** Rendered under the name, e.g. the branch selector. */
  below?: ReactNode
}) {
  return (
    <div className="flex items-center gap-3">
      <Link
        to={backTo}
        className="text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft className="h-4 w-4" />
      </Link>
      <div>
        <div className="flex items-center gap-3">
          {isLoading ? (
            <Skeleton className="h-7 w-64" />
          ) : (
            <h1 className="text-2xl font-bold tracking-tight font-mono">
              {fullName}
            </h1>
          )}
          {isPrivate && (
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
          {trailing}
        </div>
        {below}
      </div>
    </div>
  )
}
