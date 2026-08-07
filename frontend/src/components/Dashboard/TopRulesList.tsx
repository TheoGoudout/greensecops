import type { TopRuleStat } from "@/client"
import { RuleSlugChip } from "@/components/RuleSlugChip"
import { SeverityChip } from "@/components/SeverityChip"

/**
 * The rules accounting for the most open findings on one engine — the "fix
 * these first" list, and the most directly actionable thing on the page.
 *
 * The bar is scaled against the worst rule in the list rather than the
 * engine's total, so the shape stays readable when one rule dominates.
 */
export function TopRulesList({
  rules,
  emptyLabel = "No open findings.",
}: {
  rules: TopRuleStat[]
  emptyLabel?: string
}) {
  if (rules.length === 0) {
    return (
      <p className="text-sm text-muted-foreground text-center py-6">
        {emptyLabel}
      </p>
    )
  }
  const max = Math.max(...rules.map((r) => r.open), 1)

  return (
    <ul className="flex flex-col gap-2.5">
      {rules.map((rule) => (
        <li key={rule.rule_id} className="flex flex-col gap-1">
          <div className="flex items-baseline justify-between gap-3 min-w-0">
            <span className="flex items-center gap-2 min-w-0">
              <SeverityChip severity={rule.severity} />
              <span className="text-sm truncate" title={rule.title}>
                {rule.title}
              </span>
            </span>
            <span className="text-sm font-medium tabular-nums shrink-0">
              {rule.open}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <div className="h-1.5 flex-1 rounded-full bg-muted overflow-hidden">
              <div
                className="h-full rounded-full bg-primary"
                style={{ width: `${Math.round((rule.open / max) * 100)}%` }}
              />
            </div>
            <RuleSlugChip className="shrink-0">{rule.slug}</RuleSlugChip>
          </div>
        </li>
      ))}
    </ul>
  )
}
