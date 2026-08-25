import type { Severity } from "@/client"

export const SEVERITY_ORDER: Severity[] = [
  "critical",
  "high",
  "medium",
  "low",
  "info",
]

export const severityRank = (s: Severity): number => {
  const rank = SEVERITY_ORDER.indexOf(s)
  return rank === -1 ? 99 : rank
}
