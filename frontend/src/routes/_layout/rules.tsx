import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { useState } from "react"
import type { IssueCategory, RulePublic } from "@/client"
import { RulesService } from "@/client"
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
import useAuth from "@/hooks/useAuth"

export const Route = createFileRoute("/_layout/rules")({
  component: Rules,
  head: () => ({
    meta: [{ title: "Rules - GreenSecOps" }],
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
    <div className="flex items-start justify-between gap-4 px-6 py-4">
      <div className="flex items-start gap-3 min-w-0">
        <CategoryIcon category={rule.category} className="mt-0.5 shrink-0" />
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <p className="text-sm font-medium">{rule.title}</p>
            <SeverityChip severity={rule.severity} />
          </div>
          <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">
            {rule.description}
          </p>
          <p className="text-xs text-muted-foreground mt-0.5 font-mono">
            {rule.slug}
          </p>
        </div>
      </div>

      {canToggle ? (
        <Button
          variant={rule.enabled ? "default" : "outline"}
          size="sm"
          className="shrink-0"
          onClick={() => toggleMutation.mutate(!rule.enabled)}
          disabled={toggleMutation.isPending}
        >
          {rule.enabled ? "Enabled" : "Disabled"}
        </Button>
      ) : (
        <span
          className={`text-xs px-2 py-0.5 rounded-full shrink-0 ${
            rule.enabled
              ? "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300"
              : "bg-muted text-muted-foreground"
          }`}
        >
          {rule.enabled ? "Enabled" : "Disabled"}
        </span>
      )}
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
            {CATEGORIES.map((c) => (
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
              {rules.map((rule) => (
                <RuleRow key={rule.id} rule={rule} canToggle={isSuperuser} />
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
