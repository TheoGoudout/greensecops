import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { useState } from "react"
import type { IssueCategory, IssueSeverity } from "@/client"
import { IssuesService } from "@/client"
import { CategoryIcon } from "@/components/CategoryIcon"
import { GenerateFixButton } from "@/components/GenerateFixButton"
import { SeverityChip } from "@/components/SeverityChip"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"

export const Route = createFileRoute("/_layout/issues")({
  component: Issues,
  head: () => ({
    meta: [{ title: "Issues - GreenSecOps" }],
  }),
})

const CATEGORIES: Array<{ value: IssueCategory | "all"; label: string }> = [
  { value: "all", label: "All categories" },
  { value: "energy", label: "⚡ Energy" },
  { value: "reliability", label: "🛡️ Reliability" },
  { value: "security", label: "🔒 Security" },
  { value: "performance", label: "🚀 Performance" },
  { value: "maintainability", label: "🔧 Maintainability" },
]

const SEVERITIES: Array<{ value: IssueSeverity | "all"; label: string }> = [
  { value: "all", label: "All severities" },
  { value: "critical", label: "Critical" },
  { value: "high", label: "High" },
  { value: "medium", label: "Medium" },
  { value: "low", label: "Low" },
  { value: "info", label: "Info" },
]

const PAGE_SIZE = 50

function Issues() {
  const [category, setCategory] = useState<IssueCategory | "all">("all")
  const [severity, setSeverity] = useState<IssueSeverity | "all">("all")
  const [unfixed, setUnfixed] = useState(false)
  const [page, setPage] = useState(0)

  const {
    data: issues,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["issues", { category, severity, unfixed, page }],
    queryFn: () =>
      IssuesService.listIssues({
        category: category === "all" ? undefined : category,
        severity: severity === "all" ? undefined : severity,
        unfixed: unfixed || undefined,
        skip: page * PAGE_SIZE,
        limit: PAGE_SIZE,
      }),
  })

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Issues</h1>
        <p className="text-muted-foreground">
          Browse and fix issues found across all analyses
        </p>
      </div>

      <div className="flex flex-wrap gap-3">
        <Select
          value={category}
          onValueChange={(v) => {
            setCategory(v as IssueCategory | "all")
            setPage(0)
          }}
        >
          <SelectTrigger className="w-48">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {CATEGORIES.map((c) => (
              <SelectItem key={c.value} value={c.value}>
                {c.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select
          value={severity}
          onValueChange={(v) => {
            setSeverity(v as IssueSeverity | "all")
            setPage(0)
          }}
        >
          <SelectTrigger className="w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SEVERITIES.map((s) => (
              <SelectItem key={s.value} value={s.value}>
                {s.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Button
          variant={unfixed ? "default" : "outline"}
          size="sm"
          onClick={() => {
            setUnfixed((v) => !v)
            setPage(0)
          }}
        >
          Open only
        </Button>
      </div>

      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="flex flex-col gap-2 p-6">
              {[...Array(6)].map((_, i) => (
                <Skeleton key={i} className="h-14 w-full" />
              ))}
            </div>
          ) : isError ? (
            <p className="text-sm text-destructive p-6">
              Failed to load issues.
            </p>
          ) : !issues?.length ? (
            <p className="text-sm text-muted-foreground p-6 text-center">
              No issues match the selected filters.
            </p>
          ) : (
            <div className="divide-y">
              {issues.map((issue) => (
                <div
                  key={issue.id}
                  className="flex items-start gap-3 px-6 py-4"
                >
                  <CategoryIcon
                    category={issue.category}
                    className="mt-0.5 shrink-0 text-base"
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <SeverityChip severity={issue.severity} />
                      <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-mono bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300">
                        {issue.rule_slug}
                      </span>
                      <span className="text-sm">{issue.message}</span>
                    </div>
                    {issue.line_start !== null && (
                      <p className="text-xs text-muted-foreground mt-0.5">
                        line {issue.line_start}
                        {issue.line_end && issue.line_end !== issue.line_start
                          ? `–${issue.line_end}`
                          : ""}
                      </p>
                    )}
                  </div>
                  <GenerateFixButton
                    issueId={issue.id}
                    fixStatus={issue.fix_status}
                  />
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <div className="flex items-center justify-between">
        <Button
          variant="outline"
          size="sm"
          onClick={() => setPage((p) => p - 1)}
          disabled={page === 0}
        >
          Previous
        </Button>
        <span className="text-xs text-muted-foreground">Page {page + 1}</span>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setPage((p) => p + 1)}
          disabled={!issues || issues.length < PAGE_SIZE}
        >
          Next
        </Button>
      </div>
    </div>
  )
}
