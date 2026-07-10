import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Zap } from "lucide-react"
import { useMemo, useState } from "react"
import { toast } from "sonner"
import { FixesService, IssuesService, RepositoriesService } from "@/client"
import { IssueRow } from "@/components/IssueRow"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { severityRank } from "@/lib/severity"
import {
  groupByWorkflowFile,
  PAGE_SIZE,
  workflowLabel,
} from "@/lib/workflow-utils"
import { apiErrorDetail } from "@/utils"

type IssuesSearch = { branch?: string }

export const Route = createFileRoute("/_layout/repositories/$repoId/issues")({
  component: IssuesPage,
  validateSearch: (search: Record<string, unknown>): IssuesSearch => ({
    branch: typeof search.branch === "string" ? search.branch : undefined,
  }),
  head: () => ({
    meta: [{ title: "Issues - GreenSecOps" }],
  }),
})

function IssuesPage() {
  const { repoId } = Route.useParams()
  const { branch } = Route.useSearch()
  const navigate = Route.useNavigate()
  const queryClient = useQueryClient()
  const [unfixed, setUnfixed] = useState(false)
  const [deselectedIds, setDeselectedIds] = useState<Set<string>>(new Set())
  const [page, setPage] = useState(0)

  const { data: branches } = useQuery({
    queryKey: ["branches", repoId],
    queryFn: () => RepositoriesService.listRepositoryBranches({ repoId }),
  })

  const { data: issues, isLoading } = useQuery({
    queryKey: ["issues", "repo", repoId, { unfixed, branch }],
    queryFn: () =>
      IssuesService.listIssues({
        repoId,
        branch: branch || undefined,
        unfixed: unfixed || undefined,
        limit: 200,
      }),
  })

  const selectedIds = useMemo(() => {
    if (!issues) return []
    return issues.filter((i) => !deselectedIds.has(i.id)).map((i) => i.id)
  }, [issues, deselectedIds])

  const batchFixMutation = useMutation({
    mutationFn: () =>
      FixesService.triggerFixGenerationForRepo({
        repoId,
        force: true,
        requestBody:
          selectedIds.length === issues?.length
            ? undefined
            : { issue_ids: selectedIds },
      }),
    onSuccess: (data) => {
      toast.success(`Queued ${data.queued} fix${data.queued !== 1 ? "es" : ""}`)
      queryClient.invalidateQueries({ queryKey: ["issues", "repo", repoId] })
      queryClient.invalidateQueries({ queryKey: ["fixes", "repo", repoId] })
    },
    onError: (error) =>
      toast.error("Failed to queue fixes", {
        description: apiErrorDetail(error),
      }),
  })

  const sortedIssues = useMemo(
    () =>
      [...(issues ?? [])].sort(
        (a, b) =>
          severityRank(a.severity) - severityRank(b.severity) ||
          a.rule_slug.localeCompare(b.rule_slug),
      ),
    [issues],
  )

  const pagedIssues = useMemo(
    () => sortedIssues.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE),
    [sortedIssues, page],
  )

  const pagedIssuesByWorkflow = useMemo(
    () => groupByWorkflowFile(pagedIssues),
    [pagedIssues],
  )

  const allSelected = !issues || issues.length === 0 || deselectedIds.size === 0
  const noneSelected = !issues || issues.every((i) => deselectedIds.has(i.id))

  function toggleIssue(id: string) {
    setDeselectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function selectAll() {
    setDeselectedIds(new Set())
  }

  function deselectAll() {
    setDeselectedIds(new Set(issues?.map((i) => i.id) ?? []))
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3 flex-wrap">
        <p className="text-sm text-muted-foreground">Branch:</p>
        <Select
          value={branch ?? ""}
          onValueChange={(val) => {
            navigate({ search: val ? { branch: val } : {} })
            setPage(0)
          }}
        >
          <SelectTrigger className="w-48 h-8 text-xs">
            <SelectValue placeholder="All branches" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="">All branches</SelectItem>
            {(branches ?? []).map((b) => (
              <SelectItem key={b} value={b}>
                {b}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {!!issues?.length && (
        <div className="flex items-center gap-3 flex-wrap">
          <Button
            variant={unfixed ? "default" : "outline"}
            size="sm"
            onClick={() => {
              setUnfixed((v) => !v)
              setDeselectedIds(new Set())
              setPage(0)
            }}
          >
            Open only
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="text-xs"
            onClick={allSelected ? deselectAll : selectAll}
            disabled={!issues?.length}
          >
            {allSelected ? "Deselect all" : "Select all"}
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="gap-2"
            onClick={() => batchFixMutation.mutate()}
            disabled={batchFixMutation.isPending || noneSelected}
          >
            <Zap className="h-4 w-4" />
            {batchFixMutation.isPending
              ? "Queuing…"
              : `Fix selected${selectedIds.length > 0 ? ` (${selectedIds.length})` : ""}`}
          </Button>
        </div>
      )}

      {isLoading ? (
        <div className="flex flex-col gap-2">
          {[...Array(5)].map((_, i) => (
            <Skeleton key={i} className="h-14 w-full" />
          ))}
        </div>
      ) : !issues?.length ? (
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground text-sm">
            No issues found.
          </CardContent>
        </Card>
      ) : (
        [...pagedIssuesByWorkflow.entries()].map(([wfPath, wfIssues]) => {
          const allGroupSelected = wfIssues.every(
            (i) => !deselectedIds.has(i.id),
          )
          return (
            <Card key={wfPath || "__unknown__"}>
              <CardHeader className="pb-2 pt-4">
                <CardTitle className="text-sm font-mono flex items-center gap-2 min-w-0">
                  <Checkbox
                    checked={allGroupSelected}
                    onCheckedChange={() => {
                      setDeselectedIds((prev) => {
                        const next = new Set(prev)
                        if (allGroupSelected) {
                          for (const i of wfIssues) next.add(i.id)
                        } else {
                          for (const i of wfIssues) next.delete(i.id)
                        }
                        return next
                      })
                    }}
                    className="shrink-0"
                  />
                  <span className="text-muted-foreground font-sans font-normal text-xs shrink-0">
                    Workflow:
                  </span>
                  <span className="truncate min-w-0 flex-1">
                    {workflowLabel(wfPath)}
                  </span>
                  <span className="text-muted-foreground font-normal text-xs shrink-0">
                    ({wfIssues.length})
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <div className="divide-y">
                  {wfIssues.map((issue) => (
                    <IssueRow
                      key={issue.id}
                      issue={issue}
                      repoId={repoId}
                      checked={!deselectedIds.has(issue.id)}
                      onCheckedChange={() => toggleIssue(issue.id)}
                    />
                  ))}
                </div>
              </CardContent>
            </Card>
          )
        })
      )}
      {(issues?.length ?? 0) > PAGE_SIZE && (
        <div className="flex items-center justify-between py-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page === 0}
            onClick={() => setPage((p) => p - 1)}
          >
            Previous
          </Button>
          <span className="text-xs text-muted-foreground">
            Page {page + 1} of {Math.ceil((issues?.length ?? 0) / PAGE_SIZE)}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={(page + 1) * PAGE_SIZE >= (issues?.length ?? 0)}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </Button>
        </div>
      )}
    </div>
  )
}
