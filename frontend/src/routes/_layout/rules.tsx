import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { useState } from "react"
import type { IssueCategory, RulePublic } from "@/client"
import { RulesService } from "@/client"
import { CategoryIcon } from "@/components/CategoryIcon"
import { SeverityChip } from "@/components/SeverityChip"
import { Card, CardContent } from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import useAuth from "@/hooks/useAuth"
import { CATEGORY_SELECT_OPTIONS } from "@/lib/issue-constants"
import { severityRank } from "@/lib/severity"

export const Route = createFileRoute("/_layout/rules")({
  component: Rules,
  head: () => ({
    meta: [{ title: "Rules - GreenSecOps" }],
  }),
})

function RuleRow({
  rule,
  canToggle,
}: {
  rule: RulePublic
  canToggle: boolean
}) {
  const queryClient = useQueryClient()
  const toggleMutation = useMutation({
    mutationFn: (enabled: boolean) =>
      RulesService.toggleRule({ ruleId: rule.id, enabled }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["rules"] })
    },
  })

  return (
    <div className="flex items-center justify-between gap-4 px-6 py-4">
      <div className="flex items-center gap-3 min-w-0">
        <CategoryIcon category={rule.category} className="shrink-0" />
        <div className="min-w-0">
          <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-mono bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300">
            {rule.slug}
          </span>
          <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">
            {rule.description}
          </p>
        </div>
      </div>
      <div className="flex items-center gap-3 shrink-0">
        <SeverityChip severity={rule.severity} />
        {canToggle ? (
          <Switch
            checked={rule.enabled}
            onCheckedChange={(v) => toggleMutation.mutate(v)}
            disabled={toggleMutation.isPending}
          />
        ) : (
          <Switch checked={rule.enabled} onCheckedChange={() => {}} disabled />
        )}
      </div>
    </div>
  )
}

function Rules() {
  const { user } = useAuth()
  const [category, setCategory] = useState<IssueCategory | "all">("all")

  const {
    data: rules,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["rules", { category }],
    queryFn: () =>
      RulesService.listRules({
        category: category === "all" ? undefined : category,
        limit: 200,
      }),
  })

  const isSuperuser = user?.is_superuser ?? false

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Rules</h1>
        <p className="text-muted-foreground">
          {isSuperuser
            ? "View and toggle analysis rules (superuser)"
            : "View analysis rules and their severities"}
        </p>
      </div>

      <div className="flex gap-3">
        <Select
          value={category}
          onValueChange={(v) => setCategory(v as IssueCategory | "all")}
        >
          <SelectTrigger className="w-48">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {CATEGORY_SELECT_OPTIONS.map((c) => (
              <SelectItem key={c.value} value={c.value}>
                {c.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="flex flex-col gap-2 p-6">
              {[...Array(8)].map((_, i) => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </div>
          ) : isError ? (
            <p className="text-sm text-destructive p-6">
              Failed to load rules.
            </p>
          ) : !rules?.length ? (
            <p className="text-sm text-muted-foreground p-6 text-center">
              No rules found.
            </p>
          ) : (
            <div className="divide-y">
              {[...rules]
                .sort(
                  (a, b) =>
                    severityRank(a.severity) - severityRank(b.severity) ||
                    a.title.localeCompare(b.title),
                )
                .map((rule) => (
                  <RuleRow key={rule.id} rule={rule} canToggle={isSuperuser} />
                ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
