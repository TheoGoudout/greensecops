import type { LucideIcon } from "lucide-react"
import type { ReactNode } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

/**
 * One headline number with an optional sub-line.
 *
 * The value uses the font's proportional figures, not `tabular-nums` — equal
 * width digits make a short number look loose at this size. Tabular figures
 * belong in the columns of numbers this dashboard renders elsewhere.
 */
export function StatCard({
  icon: Icon,
  title,
  value,
  hint,
  loading,
  accessory,
}: {
  icon: LucideIcon
  title: string
  value: string | number
  hint?: ReactNode
  loading: boolean
  accessory?: ReactNode
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>
        {loading ? (
          <Skeleton className="h-8 w-16" />
        ) : (
          <>
            <div className="flex items-center gap-2">
              <p className="text-2xl font-bold">{value}</p>
              {accessory}
            </div>
            {hint && (
              <p className="text-xs text-muted-foreground mt-0.5">{hint}</p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
