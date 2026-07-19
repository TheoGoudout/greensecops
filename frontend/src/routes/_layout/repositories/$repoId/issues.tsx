import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Activity, Loader2, RefreshCw, Wand2, Zap } from "lucide-react"
import { useMemo, useState } from "react"
import { toast } from "sonner"
import {
  FixesService,
  type FixPublic,
  type FixStatus,
  IssuesService,
  TelemetryService,
} from "@/client"
import { IssueRow } from "@/components/IssueRow"
import { RuntimeFindingRow } from "@/components/RuntimeFindingRow"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Skeleton } from "@/components/ui/skeleton"
import { useRepository } from "@/hooks/useRepository"
import { severityRank } from "@/lib/severity"
import {
  groupByWorkflowFile,
  PAGE_SIZE,
  workflowLabel,
} from "@/lib/workflow-utils"
import { Route as RepoRoute } from "@/routes/_layout/repositories/$repoId"
import { apiErrorDetail } from "@/utils"

export const Route = createFileRoute("/_layout/repositories/$repoId/issues")({
  component: IssuesPage,
  head: () => ({
    meta: [{ title: "Issues - GreenSecOps" }],
  }),
})

const IN_FLIGHT_STATUSES: FixStatus[] = ["pending", "generating", "delivering"]

// Mirrors the backend eligibility rules: a fix a worker is processing cannot
// be regenerated out from under it, and merged code changes are already
// applied.
const isRegenerable = (fix: FixPublic) =>
  !IN_FLIGHT_STATUSES.includes(fix.status) && fix.pr_state !== "merged"

function IssuesPage() {
  const { repoId } = Route.useParams()
  const { branch } = RepoRoute.useSearch()
  const queryClient = useQueryClient()
  const [unfixed, setUnfixed] = useState(false)
  const [showIgnored, setShowIgnored] = useState(false)
  const [deselectedIds, setDeselectedIds] = useState<Set<string>>(new Set())
  const [page, setPage] = useState(0)

  const { isAccessible } = useRepository(repoId)

  const { data: issues, isLoading } = useQuery({
    queryKey: ["issues", "repo", repoId, { unfixed, branch, showIgnored }],
    queryFn: () =>
      IssuesService.listIssues({
        repoId,
        branch: branch || undefined,
        unfixed: unfixed || undefined,
        includeIgnored: showIgnored || undefined,
        limit: 200,
      }),
  })

  // Runtime (telemetry) findings are shown as a distinct, read-only section
  // above the static issues — they carry no severity/status/fix lifecycle and
  // must not be mistaken for or folded into static violations.
  const { data: runtimeFindings } = useQuery({
    queryKey: ["telemetry", "findings", repoId],
    queryFn: () => TelemetryService.getTelemetryFindings({ repoId }),
  })

  const selectedIds = useMemo(() => {
    if (!issues) return []
    // Ignored issues are muted — never part of a fix batch.
    return issues
      .filter((i) => i.status !== "ignored" && !deselectedIds.has(i.id))
      .map((i) => i.id)
  }, [issues, deselectedIds])

  const { data: fixes } = useQuery({
    queryKey: ["fixes", "repo", repoId],
    queryFn: () => FixesService.listFixes({ repoId, limit: 100 }),
  })

  const fixByWfPath = useMemo(() => {
    const map = new Map<string, FixPublic>()
    for (const fix of fixes ?? []) {
      if (fix.workflow_file_path) map.set(fix.workflow_file_path, fix)
    }
    return map
  }, [fixes])

  const wfFixMutation = useMutation({
    mutationFn: (vars: { wfPath: string; issueIds: string[] }) =>
      FixesService.triggerFixGenerationForRepo({
        repoId,
        force: true,
        requestBody: { issue_ids: vars.issueIds },
      }),
    onSuccess: () => {
      toast.success("Fix generation queued")
      queryClient.invalidateQueries({ queryKey: ["issues", "repo", repoId] })
      queryClient.invalidateQueries({ queryKey: ["fixes", "repo", repoId] })
    },
    onError: (error) =>
      toast.error("Failed to queue fix", {
        description: apiErrorDetail(error),
      }),
  })

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

  const regenerateWorkflowMutation = useMutation({
    mutationFn: (fixId: string) =>
      FixesService.regenerateFixesForWorkflow({ fixId }),
    onSuccess: () => {
      toast.success("Fix queued for regeneration")
      queryClient.invalidateQueries({ queryKey: ["issues", "repo", repoId] })
      queryClient.invalidateQueries({ queryKey: ["fixes", "repo", repoId] })
    },
    onError: (error) =>
      toast.error("Failed to regenerate fix", {
        description: apiErrorDetail(error),
      }),
  })

  const regenerateRepoMutation = useMutation({
    mutationFn: () => FixesService.regenerateFixesForRepo({ repoId }),
    onSuccess: () => {
      toast.success("All fixes queued for regeneration")
      queryClient.invalidateQueries({ queryKey: ["issues", "repo", repoId] })
      queryClient.invalidateQueries({ queryKey: ["fixes", "repo", repoId] })
    },
    onError: (error) =>
      toast.error("Failed to regenerate fixes", {
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

  const allIssuesByWorkflow = useMemo(
    () => groupByWorkflowFile(sortedIssues),
    [sortedIssues],
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
      {/* Filter toggles stay available even when the current view is empty, so
          ignored issues can always be revealed and unignored. Batch actions
          below are gated on there being visible issues. */}
      {!isLoading && (
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
            variant={showIgnored ? "default" : "outline"}
            size="sm"
            onClick={() => {
              setShowIgnored((v) => !v)
              setDeselectedIds(new Set())
              setPage(0)
            }}
          >
            Show ignored
          </Button>
          {!!issues?.length && (
            <>
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
                disabled={
                  !isAccessible || batchFixMutation.isPending || noneSelected
                }
              >
                <Zap className="h-4 w-4" />
                {batchFixMutation.isPending
                  ? "Queuing…"
                  : `Fix selected${selectedIds.length > 0 ? ` (${selectedIds.length})` : ""}`}
              </Button>
              {fixes?.some(isRegenerable) && (
                <Button
                  variant="outline"
                  size="sm"
                  className="gap-2"
                  onClick={() => regenerateRepoMutation.mutate()}
                  disabled={!isAccessible || regenerateRepoMutation.isPending}
                >
                  <RefreshCw className="h-4 w-4" />
                  {regenerateRepoMutation.isPending
                    ? "Queuing…"
                    : "Regenerate all fixes"}
                </Button>
              )}
            </>
          )}
        </div>
      )}

      {!!runtimeFindings?.length && (
        <Card>
          <CardHeader className="pb-2 pt-4">
            <CardTitle className="text-sm flex items-center gap-2">
              <Activity className="h-4 w-4 text-amber-600 dark:text-amber-400" />
              Runtime recommendations
              <span className="text-muted-foreground font-normal text-xs">
                ({runtimeFindings.length})
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <div className="divide-y">
              {runtimeFindings.map((finding) => (
                <RuntimeFindingRow key={finding.id} finding={finding} />
              ))}
            </div>
          </CardContent>
        </Card>
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
            {runtimeFindings?.length
              ? "No static issues found."
              : "No issues found."}
          </CardContent>
        </Card>
      ) : (
        [...pagedIssuesByWorkflow.entries()]
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([wfPath, wfIssues]) => {
            const allGroupSelected = wfIssues.every(
              (i) => !deselectedIds.has(i.id),
            )
            const wfFix = fixByWfPath.get(wfPath)
            const wfFixInFlight =
              !!wfFix && IN_FLIGHT_STATUSES.includes(wfFix.status)
            const isRegenerating =
              regenerateWorkflowMutation.isPending &&
              regenerateWorkflowMutation.variables === wfFix?.id
            return (
              <Card key={wfPath || "__unknown__"}>
                <CardHeader className="pb-2 pt-4">
                  <div className="flex items-center justify-between gap-4 min-w-0">
                    <CardTitle className="text-sm font-mono flex items-center gap-2 min-w-0 flex-1">
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
                    {wfFix && isRegenerable(wfFix) ? (
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 text-xs gap-1.5 shrink-0"
                        onClick={() =>
                          regenerateWorkflowMutation.mutate(wfFix.id)
                        }
                        disabled={
                          !isAccessible ||
                          isRegenerating ||
                          regenerateRepoMutation.isPending
                        }
                      >
                        {isRegenerating ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : (
                          <RefreshCw className="h-3 w-3" />
                        )}
                        {isRegenerating ? "Queuing…" : "Regenerate fix"}
                      </Button>
                    ) : (
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 text-xs gap-1.5 shrink-0"
                        onClick={() =>
                          wfFixMutation.mutate({
                            wfPath,
                            issueIds: (
                              allIssuesByWorkflow.get(wfPath) ?? []
                            ).map((i) => i.id),
                          })
                        }
                        disabled={
                          !isAccessible ||
                          wfFixInFlight ||
                          (wfFixMutation.isPending &&
                            wfFixMutation.variables?.wfPath === wfPath)
                        }
                      >
                        {wfFixInFlight ||
                        (wfFixMutation.isPending &&
                          wfFixMutation.variables?.wfPath === wfPath) ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : (
                          <Wand2 className="h-3 w-3" />
                        )}
                        {wfFixInFlight
                          ? "Generating…"
                          : wfFixMutation.isPending &&
                              wfFixMutation.variables?.wfPath === wfPath
                            ? "Queuing…"
                            : "Generate fix"}
                      </Button>
                    )}
                  </div>
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
                        isAccessible={isAccessible}
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
