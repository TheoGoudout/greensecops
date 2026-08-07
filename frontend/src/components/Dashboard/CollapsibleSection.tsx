import type { LucideIcon } from "lucide-react"
import { ChevronDown, ChevronRight } from "lucide-react"
import type { ReactNode } from "react"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { cn } from "@/lib/utils"

/**
 * A dashboard section that folds away.
 *
 * The header keeps its summary chips visible when collapsed — a folded
 * section still has to answer "is anything wrong in here", or folding it costs
 * the reader the very thing the dashboard is for.
 *
 * Hand-rolled rather than a Radix Collapsible: no such primitive is installed,
 * and this matches the existing disclosure pattern in the static-analysis page.
 */
export function CollapsibleSection({
  icon: Icon,
  title,
  description,
  summary,
  open,
  onToggle,
  children,
  testId,
}: {
  icon: LucideIcon
  title: string
  description?: string
  summary?: ReactNode
  open: boolean
  onToggle: () => void
  children: ReactNode
  testId?: string
}) {
  const contentId = `section-${title.toLowerCase().replace(/\s+/g, "-")}`

  return (
    <Card data-testid={testId}>
      {/* Card already carries py-6; the extra pb only earns its place when
          there is content below it, otherwise a folded section sits
          bottom-heavy. */}
      <CardHeader className={cn(open && "pb-3")}>
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={open}
            aria-controls={contentId}
            className="flex items-center gap-2 min-w-0 text-left group"
          >
            {open ? (
              <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground transition-colors group-hover:text-foreground" />
            ) : (
              <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground transition-colors group-hover:text-foreground" />
            )}
            <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
            <span className="flex flex-col min-w-0">
              <span className="text-base font-semibold leading-none truncate">
                {title}
              </span>
              {description && (
                <span className="text-xs font-normal text-muted-foreground mt-1 truncate">
                  {description}
                </span>
              )}
            </span>
          </button>
          {summary && (
            <div className="flex items-center gap-3 shrink-0">{summary}</div>
          )}
        </div>
      </CardHeader>
      <CardContent
        id={contentId}
        className={cn("flex flex-col gap-6", !open && "hidden")}
      >
        {children}
      </CardContent>
    </Card>
  )
}
