import type { IssueCategory, IssueSeverity } from "@/client"
import { IssueCategorySchema } from "@/client/schemas.gen"

export const ISSUE_CATEGORIES: IssueCategory[] = [...IssueCategorySchema.enum]

export const CATEGORY_SELECT_OPTIONS: Array<{
  value: IssueCategory | "all"
  label: string
}> = [
  { value: "all", label: "All categories" },
  { value: "energy", label: "⚡ Energy" },
  { value: "reliability", label: "🛡️ Reliability" },
  { value: "security", label: "🔒 Security" },
  { value: "performance", label: "🚀 Performance" },
  { value: "maintainability", label: "🔧 Maintainability" },
]

export const SEVERITY_SELECT_OPTIONS: Array<{
  value: IssueSeverity | "all"
  label: string
}> = [
  { value: "all", label: "All severities" },
  { value: "critical", label: "Critical" },
  { value: "high", label: "High" },
  { value: "medium", label: "Medium" },
  { value: "low", label: "Low" },
  { value: "info", label: "Info" },
]
