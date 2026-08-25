import type { Category, EngineOverview } from "@/client"
import { CATEGORY_META } from "@/components/CategoryIcon"
import { ENGINE_META } from "@/lib/engine-meta"
import { ISSUE_CATEGORIES } from "@/lib/issue-constants"
import { cn } from "@/lib/utils"

/**
 * Open findings per category, per engine — "where is the work, and whose is
 * it", in one grid.
 *
 * A heatmap rather than a four-series radar or grouped bar. The data is a grid
 * of magnitudes, which is what a heatmap is for; and it needs exactly one hue,
 * which sidesteps the fact that the app's four chart tokens cannot be told
 * apart safely on a dark surface (chart-1 and chart-4 are both greens, ΔE 11.2
 * under normal vision — below the readable floor).
 *
 * Every cell shows its own count, so the color is a second channel and the
 * grid doubles as its own table view.
 */

// Four bins, not a continuous scale: adjacent steps of a continuous ramp are
// indistinguishable, and four is what stays separable. Tokens are defined in
// index.css and re-stepped for dark mode there.
const HEAT_STEPS = [
  { fill: "bg-heat-1", ink: "text-white" },
  { fill: "bg-heat-2", ink: "text-white" },
  { fill: "bg-heat-3", ink: "text-white" },
  { fill: "bg-heat-4", ink: "text-white dark:text-red-950" },
]

/**
 * Bin by quartile of the *distinct* non-zero counts, not by fraction of the
 * maximum.
 *
 * Finding counts are heavily skewed: one noisy rule on one engine produces an
 * outlier several times larger than everything else, and a linear scale then
 * collapses every other cell into the lightest bin — a grid where 2 and 140
 * look the same. Ranking distinct values guarantees all four steps get used
 * and keeps the ordering honest, since the exact count is printed in the cell
 * either way.
 */
function makeHeatBinner(values: number[]) {
  const distinct = [...new Set(values.filter((v) => v > 0))].sort(
    (a, b) => a - b,
  )
  return (value: number): (typeof HEAT_STEPS)[number] | null => {
    if (value <= 0) return null
    if (distinct.length <= 1) return HEAT_STEPS[HEAT_STEPS.length - 1]
    const rank = distinct.indexOf(value) / (distinct.length - 1)
    const index = Math.min(
      Math.floor(rank * HEAT_STEPS.length),
      HEAT_STEPS.length - 1,
    )
    return HEAT_STEPS[index]
  }
}

export function CategoryEngineHeatmap({
  engines,
}: {
  engines: EngineOverview[]
}) {
  const openFor = (engine: EngineOverview, category: Category) =>
    engine.findings.by_category.find((c) => c.category === category)?.open ?? 0

  const cellValues = engines.flatMap((engine) =>
    ISSUE_CATEGORIES.map((category) => openFor(engine, category)),
  )
  const heatStep = makeHeatBinner(cellValues)
  const grandTotal = engines.reduce((sum, e) => sum + e.findings.open, 0)

  if (grandTotal === 0) {
    return (
      <p className="text-sm text-muted-foreground text-center py-6">
        No open findings on any engine — nothing to plot yet.
      </p>
    )
  }

  // Inline rather than a Tailwind arbitrary value: the column count comes from
  // the data, and Tailwind only extracts class names that appear literally in
  // the source — an interpolated `grid-cols-[...]` would never be generated.
  const columns = {
    gridTemplateColumns: `minmax(6rem,1fr) repeat(${engines.length},minmax(3.5rem,0.7fr))`,
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="overflow-x-auto">
        <div className="min-w-[26rem]">
          <div className="grid gap-1 pb-1" style={columns}>
            <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide self-end">
              Category
            </span>
            {engines.map((engine) => (
              <span
                key={engine.engine}
                className="text-xs font-medium text-muted-foreground text-center self-end truncate"
                title={ENGINE_META[engine.engine].label}
              >
                {ENGINE_META[engine.engine].label.split(" ")[0]}
              </span>
            ))}
          </div>
          <div className="flex flex-col gap-1">
            {ISSUE_CATEGORIES.map((category) => (
              <div key={category} className="grid gap-1" style={columns}>
                <span className="flex items-center gap-1.5 text-sm min-w-0">
                  <span aria-hidden="true">{CATEGORY_META[category].icon}</span>
                  <span className="truncate text-muted-foreground">
                    {CATEGORY_META[category].label}
                  </span>
                </span>
                {engines.map((engine) => {
                  const open = openFor(engine, category)
                  const step = heatStep(open)
                  return (
                    <div
                      key={engine.engine}
                      title={`${open} open ${CATEGORY_META[category].label.toLowerCase()} finding${
                        open === 1 ? "" : "s"
                      } — ${ENGINE_META[engine.engine].label}`}
                      className={cn(
                        "flex h-8 items-center justify-center rounded text-xs tabular-nums transition-colors",
                        step
                          ? `${step.fill} ${step.ink} font-medium`
                          : "bg-muted/50 text-muted-foreground",
                      )}
                    >
                      {open}
                    </div>
                  )
                })}
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span>Fewer open</span>
        <span className="flex gap-0.5" aria-hidden="true">
          {HEAT_STEPS.map((step) => (
            <span
              key={step.fill}
              className={cn("h-2 w-5 rounded-sm", step.fill)}
            />
          ))}
        </span>
        <span>More</span>
      </div>
    </div>
  )
}
