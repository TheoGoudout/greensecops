import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Wand2 } from "lucide-react"
import { useState } from "react"
import type { IssueCategory, IssueSeverity } from "@/client"
import { FixesService, IssuesService } from "@/client"
import { CategoryIcon } from "@/components/CategoryIcon"
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

function GenerateFixButton({ issueId }: { issueId: string }) {
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: () => FixesService.triggerFixGeneration({ issueId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["fixes"] })
    },
  })

  return (
    <Button
      variant="outline"
      size="sm"
      className="gap-1.5 shrink-0"
      onClick={() => mutation.mutate()}
      disabled={mutation.isPending || mutation.isSuccess}
    >
      <Wand2 className="h-3.5 w-3.5" />
      {mutation.isPending
        ? "Generating…"
        : mutation.isSuccess
          ? "Queued"
          : "Generate fix"}
    </Button>
  )
}

function Issues() {
  const [category, setCategory] = useState<IssueCategory | "all">("all")
  const [severity, setSeverity] = useState<IssueSeverity | "all">("all")

  const {
    data: issues,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["issues", { category, severity }],
    queryFn: () =>
      IssuesService.listIssues({
        category: category === "all" ? undefined : category,
        severity: severity === "all" ? undefined : severity,
        limit: 200,
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
          onValueChange={(v) => setCategory(v as IssueCategory | "all")}
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
          onValueChange={(v) => setSeverity(v as IssueSeverity | "all")}
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
                  className="flex items-start justify-between gap-4 px-6 py-4"
                >
                  <div className="flex items-start gap-3 min-w-0">
                    <SeverityChip
                      severity={issue.severity}
                      className="mt-0.5 shrink-0"
                    />
                    <div className="min-w-0">
                      <p className="text-sm">{issue.message}</p>
                      <div className="flex items-center gap-2 mt-1">
                        <CategoryIcon category={issue.category} withLabel />
                        {issue.line_start !== null && (
                          <span className="text-xs text-muted-foreground">
                            · line {issue.line_start}
                            {issue.line_end &&
                            issue.line_end !== issue.line_start
                              ? `–${issue.line_end}`
                              : ""}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                  <GenerateFixButton issueId={issue.id} />
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
