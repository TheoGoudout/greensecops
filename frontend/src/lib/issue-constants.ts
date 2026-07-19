import type { IssueCategory, IssueSeverity } from "@/client"
import { IssueCategorySchema } from "@/client/schemas.gen"
import { CATEGORY_META } from "@/components/CategoryIcon"

export const ISSUE_CATEGORIES: IssueCategory[] = [...IssueCategorySchema.enum]

export const CATEGORY_SELECT_OPTIONS: Array<{
  value: IssueCategory | "all"
  label: string
}> = [
  { value: "all", label: "All categories" },
  ...ISSUE_CATEGORIES.map((c) => ({
    value: c,
    label: `${CATEGORY_META[c].icon} ${CATEGORY_META[c].label}`,
  })),
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
