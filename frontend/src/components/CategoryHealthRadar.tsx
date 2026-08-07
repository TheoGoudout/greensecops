import type { SVGProps } from "react"
import { useState } from "react"
import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
} from "recharts"
import type { IssueCategory } from "@/client"
import { CATEGORY_META } from "@/components/CategoryIcon"
import { WidgetPagination } from "@/components/Common/WidgetPagination"
import { Checkbox } from "@/components/ui/checkbox"
import { cn } from "@/lib/utils"

/**
 * One plotted series. Deliberately not named after repositories: the axes are
 * the five issue categories, which every analysis engine shares, so the same
 * chart can plot repos, scan targets or engines depending on who calls it.
 */
export interface CategoryHealthSeries {
  id: string
  name: string
  values: Record<IssueCategory, number>
}

interface CategoryHealthRadarProps {
  categories: IssueCategory[]
  series: CategoryHealthSeries[]
  toggledIds: Set<string>
  onToggle: (id: string) => void
  /** Describes what the series are, for screen readers. */
  ariaLabel?: string
  legendTestId?: string
}

const LEGEND_PAGE_SIZE = 8

// Custom tick so the label can carry a responsive Tailwind font size —
// Recharts' `tick={{ fontSize }}` object form is a fixed inline value with
// no way to shrink on narrow viewports, which is what caused the label text
// to overflow the chart's own SVG bounds at small widths.
function AxisTick({
  x = 0,
  y = 0,
  textAnchor,
  payload,
}: {
  x?: number
  y?: number
  textAnchor?: SVGProps<SVGTextElement>["textAnchor"]
  payload?: { value: string }
}) {
  return (
    <text
      x={x}
      y={y}
      textAnchor={textAnchor}
      className="fill-muted-foreground text-[10px] sm:text-[13px]"
    >
      {payload?.value}
    </text>
  )
}

// One fixed hue per slot, cycling only past the eighth concurrently-shown
// repo — assignment is by series position, never by rank/score, so a repo
// keeps its color as other repos are toggled on or off around it.
const SERIES_COLORS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
  "var(--chart-6)",
  "var(--chart-7)",
  "var(--chart-8)",
]

export function CategoryHealthRadar({
  categories,
  series,
  toggledIds,
  onToggle,
  ariaLabel = "Category health by repository",
  legendTestId = "category-health-legend",
}: CategoryHealthRadarProps) {
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [legendPageIndex, setLegendPageIndex] = useState(0)
  const visible = series.filter((s) => toggledIds.has(s.id))
  const legendPageCount = Math.ceil(series.length / LEGEND_PAGE_SIZE)
  const clampedLegendPageIndex = Math.min(
    legendPageIndex,
    Math.max(legendPageCount - 1, 0),
  )
  const pagedSeries = series.slice(
    clampedLegendPageIndex * LEGEND_PAGE_SIZE,
    (clampedLegendPageIndex + 1) * LEGEND_PAGE_SIZE,
  )

  // Recharts reads one row per axis, with each series as its own column keyed
  // by id — the shape a RadarChart with multiple <Radar> series expects.
  const chartData = categories.map((category) => {
    const row: Record<string, string | number> = {
      category: `${CATEGORY_META[category].icon} ${CATEGORY_META[category].label}`,
    }
    for (const s of series) {
      row[s.id] = s.values[category]
    }
    return row
  })

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
      <div role="img" aria-label={ariaLabel} className="h-70 w-full min-w-0">
        <ResponsiveContainer width="100%" height="100%">
          <RadarChart
            data={chartData}
            outerRadius="65%"
            margin={{ top: 8, right: 45, bottom: 8, left: 55 }}
          >
            <PolarGrid stroke="var(--border)" />
            <PolarAngleAxis dataKey="category" tick={<AxisTick />} />
            <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
            {series.map((s, index) => {
              const color = SERIES_COLORS[index % SERIES_COLORS.length]
              const isHovered = hoveredId === s.id
              const isDimmed = hoveredId !== null && !isHovered
              return (
                <Radar
                  key={s.id}
                  dataKey={s.id}
                  data-series-id={s.id}
                  hide={!toggledIds.has(s.id)}
                  stroke={color}
                  fill={color}
                  fillOpacity={isHovered ? 0.35 : 0.14}
                  strokeWidth={isHovered ? 2.5 : 1.5}
                  dot={false}
                  isAnimationActive={false}
                  style={{
                    opacity: isDimmed ? 0.15 : 1,
                    transition: "opacity 150ms ease, fill-opacity 150ms ease",
                  }}
                />
              )
            })}
          </RadarChart>
        </ResponsiveContainer>
      </div>

      <div className="flex flex-col gap-2 max-w-60 sm:shrink-0">
        <ul data-testid={legendTestId} className="flex flex-col gap-1">
          {pagedSeries.map((s) => {
            const index = series.findIndex((o) => o.id === s.id)
            const color = SERIES_COLORS[index % SERIES_COLORS.length]
            const isOn = toggledIds.has(s.id)
            const checkboxId = `category-health-series-${s.id}`
            return (
              <li key={s.id}>
                <label
                  htmlFor={checkboxId}
                  className={cn(
                    "flex items-center gap-2 rounded px-1.5 py-1 text-xs cursor-pointer hover:bg-muted/50 transition-colors",
                    hoveredId === s.id && "bg-muted/50",
                  )}
                  onMouseEnter={() => isOn && setHoveredId(s.id)}
                  onMouseLeave={() => setHoveredId(null)}
                >
                  <Checkbox
                    id={checkboxId}
                    checked={isOn}
                    onCheckedChange={() => onToggle(s.id)}
                  />
                  <span
                    aria-hidden="true"
                    className="h-2 w-2 shrink-0 rounded-full"
                    style={{ backgroundColor: color }}
                  />
                  <span className="truncate text-muted-foreground">
                    {s.name}
                  </span>
                </label>
              </li>
            )
          })}
          {visible.length === 0 && (
            <li className="px-1.5 py-1 text-xs text-muted-foreground">
              Nothing selected.
            </li>
          )}
        </ul>
        <WidgetPagination
          pageIndex={clampedLegendPageIndex}
          pageSize={LEGEND_PAGE_SIZE}
          totalItems={series.length}
          onPrevious={() => setLegendPageIndex((i) => Math.max(i - 1, 0))}
          onNext={() =>
            setLegendPageIndex((i) => Math.min(i + 1, legendPageCount - 1))
          }
          className="flex-col items-start gap-2 px-1.5 py-1 border-t-0"
        />
      </div>
    </div>
  )
}
