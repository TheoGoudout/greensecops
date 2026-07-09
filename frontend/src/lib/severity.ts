import type { IssueSeverity } from "@/client"

export const SEVERITY_ORDER: IssueSeverity[] = [
  "critical",
  "high",
  "medium",
  "low",
  "info",
]

export const severityRank = (s: IssueSeverity): number => {
  const rank = SEVERITY_ORDER.indexOf(s)
  return rank === -1 ? 99 : rank
}
