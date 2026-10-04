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
  tone = "var(--signal-1)",
}: {
  icon: LucideIcon
  title: string
  value: string | number
  hint?: ReactNode
  loading: boolean
  accessory?: ReactNode
  /** Accent colour of the icon chip and top rail; fixed per stat. */
  tone?: string
}) {
  return (
    <Card style={{ boxShadow: `inset 0 2px 0 ${tone}` }}>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
        <span
          className="flex size-8 items-center justify-center rounded-md"
          style={{
            color: tone,
            backgroundColor: `color-mix(in oklch, ${tone} 14%, transparent)`,
          }}
        >
          <Icon className="h-4 w-4" />
        </span>
      </CardHeader>
      <CardContent>
        {loading ? (
          <Skeleton className="h-8 w-16" />
        ) : (
          <>
            <div className="flex items-center gap-2">
              <p className="font-display text-3xl font-bold tracking-tight">
                {value}
              </p>
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
