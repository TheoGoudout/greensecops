import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  ChevronDown,
  ChevronRight,
  GitPullRequest,
  Loader2,
  Play,
  RefreshCw,
  Wand2,
  Zap,
} from "lucide-react"
import { useMemo, useState } from "react"
import { toast } from "sonner"
import {
  AnalysesService,
  type AnalysisPublic,
  FixesService,
  type FixPublic,
  type FixStatus,
  type IssuePublic,
  IssuesService,
  type PullRequestPublic,
  RepositoriesService,
} from "@/client"
import { GradeBadge } from "@/components/GradeBadge"
import { IssueRow } from "@/components/IssueRow"
import { StatusPill } from "@/components/StatusPill"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Skeleton } from "@/components/ui/skeleton"
import { WorkflowFileViewer } from "@/components/WorkflowFileViewer"
import { useRepository } from "@/hooks/useRepository"
import { deliverAction, labelForBranch, repoFixBranch } from "@/lib/delivery"
import { severityRank } from "@/lib/severity"
import {
  analysisStatusColor,
  analysisStatusLabel,
  fixStatusColor,
} from "@/lib/status-colors"
import { PAGE_SIZE, workflowLabel } from "@/lib/workflow-utils"
import { Route as RepoRoute } from "@/routes/_layout/repositories/$repoId"
import { apiErrorDetail } from "@/utils"

export const Route = createFileRoute(
  "/_layout/repositories/$repoId/static-analysis",
)({
  component: StaticAnalysisPage,
  head: () => ({
    meta: [{ title: "Static analysis - GreenSecOps" }],
  }),
})

const IN_FLIGHT_STATUSES: FixStatus[] = ["pending", "generating", "delivering"]

// Mirrors the backend eligibility rules: a fix a worker is processing cannot
// be regenerated out from under it, and merged code changes are already
// applied.
const isRegenerable = (fix: FixPublic) =>
  !IN_FLIGHT_STATUSES.includes(fix.status) && fix.pr_state !== "merged"

function StaticAnalysisPage() {
  const { repoId } = Route.useParams()
  const { branch } = RepoRoute.useSearch()
  const queryClient = useQueryClient()

  const { isAccessible } = useRepository(repoId)

  const [unfixed, setUnfixed] = useState(false)
  const [showIgnored, setShowIgnored] = useState(false)
  // Workflow files are the unit a fix is generated for, so batch selection is
  // per-workflow (a whole-file fix), not per-issue.
  const [deselectedPaths, setDeselectedPaths] = useState<Set<string>>(new Set())
  const [historyOpen, setHistoryOpen] = useState(false)
  const [historyPage, setHistoryPage] = useState(0)
  // Issue lists are expanded by default (a path in the set is collapsed) so
  // every issue stays discoverable and actionable, including ones whose line
  // number falls outside the current file and so aren't annotated inline.
  const [collapsedIssueLists, setCollapsedIssueLists] = useState<Set<string>>(
    new Set(),
  )

  const invalidateStatic = () => {
    queryClient.invalidateQueries({ queryKey: ["issues", "repo", repoId] })
    queryClient.invalidateQueries({ queryKey: ["fixes", "repo", repoId] })
    queryClient.invalidateQueries({ queryKey: ["analyses", repoId] })
  }

  const { data: workflowFiles, isLoading: wfLoading } = useQuery({
    queryKey: ["workflow-files", repoId, { branch }],
    queryFn: () =>
      RepositoriesService.listWorkflowFiles({
        repoId,
        branch: branch || undefined,
      }),
  })

  const { data: issues } = useQuery({
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

  const { data: fixes } = useQuery({
    queryKey: ["fixes", "repo", repoId, branch],
    queryFn: () =>
      FixesService.listFixes({
        repoId,
        branch: branch || undefined,
        limit: 100,
      }),
  })

  const { data: analyses } = useQuery({
    queryKey: ["analyses", repoId, branch],
    queryFn: () =>
      AnalysesService.listAnalyses({
        repoId,
        branch: branch || undefined,
        limit: 100,
      }),
  })

  const { data: pullRequests } = useQuery({
    queryKey: ["pull-requests", "repo", repoId],
    queryFn: () => FixesService.listPullRequests({ repoId }),
  })

  const prByBranch = useMemo(() => {
    const map = new Map<string, PullRequestPublic>()
    for (const pr of pullRequests ?? []) map.set(pr.pr_branch, pr)
    return map
  }, [pullRequests])

  const issuesByPath = useMemo(() => {
    const map = new Map<string, IssuePublic[]>()
    for (const issue of issues ?? []) {
      const path = issue.workflow_file_path ?? ""
      const list = map.get(path) ?? []
      list.push(issue)
      map.set(path, list)
    }
    for (const list of map.values()) {
      list.sort(
        (a, b) =>
          severityRank(a.severity) - severityRank(b.severity) ||
          a.rule_slug.localeCompare(b.rule_slug),
      )
    }
    return map
  }, [issues])

  const fixByPath = useMemo(() => {
    const map = new Map<string, FixPublic>()
    for (const fix of fixes ?? []) map.set(fix.workflow_file_path ?? "", fix)
    return map
  }, [fixes])

  // Latest analysis per workflow file drives the per-card grade / status.
  const latestAnalysisByPath = useMemo(() => {
    const map = new Map<string, AnalysisPublic>()
    for (const a of analyses ?? []) {
      const path = a.workflow_file_path ?? ""
      const prev = map.get(path)
      if (
        !prev ||
        new Date(a.created_at ?? 0).getTime() >
          new Date(prev.created_at ?? 0).getTime()
      ) {
        map.set(path, a)
      }
    }
    return map
  }, [analyses])

  // Workflows that carry acted-upon issues are the batch candidates.
  const selectablePaths = useMemo(
    () =>
      (workflowFiles ?? [])
        .map((wf) => wf.path)
        .filter((p) =>
          (issuesByPath.get(p) ?? []).some((i) => i.status !== "ignored"),
        ),
    [workflowFiles, issuesByPath],
  )

  const selectedPaths = useMemo(
    () => selectablePaths.filter((p) => !deselectedPaths.has(p)),
    [selectablePaths, deselectedPaths],
  )

  const selectedIssueIds = useMemo(
    () =>
      selectedPaths.flatMap((p) =>
        (issuesByPath.get(p) ?? [])
          .filter((i) => i.status !== "ignored")
          .map((i) => i.id),
      ),
    [selectedPaths, issuesByPath],
  )

  const wfFixMutation = useMutation({
    mutationFn: (vars: { issueIds: string[] }) =>
      FixesService.triggerFixGenerationForRepo({
        repoId,
        force: true,
        requestBody: { issue_ids: vars.issueIds },
      }),
    onSuccess: () => {
      toast.success("Fix generation queued")
      invalidateStatic()
    },
    onError: (error) =>
      toast.error("Failed to queue fix", {
        description: apiErrorDetail(error),
      }),
  })

  const regenerateWorkflowMutation = useMutation({
    mutationFn: (fixId: string) =>
      FixesService.regenerateFixesForWorkflow({ fixId }),
    onSuccess: () => {
      toast.success("Fix queued for regeneration")
      invalidateStatic()
    },
    onError: (error) =>
      toast.error("Failed to regenerate fix", {
        description: apiErrorDetail(error),
      }),
  })

  const batchFixMutation = useMutation({
    mutationFn: () =>
      FixesService.triggerFixGenerationForRepo({
        repoId,
        force: true,
        requestBody:
          selectedPaths.length === selectablePaths.length
            ? undefined
            : { issue_ids: selectedIssueIds },
      }),
    onSuccess: (data) => {
      toast.success(`Queued ${data.queued} fix${data.queued !== 1 ? "es" : ""}`)
      invalidateStatic()
    },
    onError: (error) =>
      toast.error("Failed to queue fixes", {
        description: apiErrorDetail(error),
      }),
  })

  const regenerateRepoMutation = useMutation({
    mutationFn: () => FixesService.regenerateFixesForRepo({ repoId }),
    onSuccess: () => {
      toast.success("All fixes queued for regeneration")
      invalidateStatic()
    },
    onError: (error) =>
      toast.error("Failed to regenerate fixes", {
        description: apiErrorDetail(error),
      }),
  })

  const analyzeWorkflowMutation = useMutation({
    mutationFn: (workflowFileId: string) =>
      AnalysesService.reanalyzeForWorkflow({ workflowFileId, force: true }),
    onSuccess: () => {
      toast.success("Analysis queued")
      invalidateStatic()
    },
    onError: (error) =>
      toast.error("Failed to trigger analysis", {
        description: apiErrorDetail(error),
      }),
  })

  const deliverWorkflowMutation = useMutation({
    mutationFn: (vars: { fixId: string; force: boolean }) =>
      FixesService.triggerWorkflowDelivery({
        force: vars.force,
        requestBody: { fix_id: vars.fixId },
      }),
    onSuccess: () => {
      toast.success("Workflow PR queued")
      queryClient.invalidateQueries({ queryKey: ["fixes", "repo", repoId] })
      queryClient.invalidateQueries({
        queryKey: ["pull-requests", "repo", repoId],
      })
    },
    onError: (error) =>
      toast.error("Failed to queue workflow PR", {
        description: apiErrorDetail(error),
      }),
  })

  const deliverRepoMutation = useMutation({
    mutationFn: (vars: { force: boolean }) =>
      FixesService.triggerRepoDelivery({ repoId, force: vars.force }),
    onSuccess: () => {
      toast.success("Repo-wide PR queued")
      queryClient.invalidateQueries({ queryKey: ["fixes", "repo", repoId] })
      queryClient.invalidateQueries({
        queryKey: ["pull-requests", "repo", repoId],
      })
    },
    onError: (error) =>
      toast.error("Failed to queue repo-wide PR", {
        description: apiErrorDetail(error),
      }),
  })

  const repoDeliverAction = labelForBranch(
    prByBranch,
    repoFixBranch(repoId),
    "PR for all workflows",
  )

  const sortedAnalyses = useMemo(
    () =>
      [...(analyses ?? [])].sort(
        (a, b) =>
          new Date(b.created_at ?? 0).getTime() -
          new Date(a.created_at ?? 0).getTime(),
      ),
    [analyses],
  )

  const pagedAnalyses = useMemo(
    () =>
      sortedAnalyses.slice(
        historyPage * PAGE_SIZE,
        (historyPage + 1) * PAGE_SIZE,
      ),
    [sortedAnalyses, historyPage],
  )

  const sortedWorkflowFiles = useMemo(
    () =>
      [...(workflowFiles ?? [])].sort((a, b) => a.path.localeCompare(b.path)),
    [workflowFiles],
  )

  const allSelected = selectablePaths.length > 0 && deselectedPaths.size === 0
  const noneSelected = selectedPaths.length === 0

  function toggleWorkflow(path: string) {
    setDeselectedPaths((prev) => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }

  function toggleIssueList(path: string) {
    setCollapsedIssueLists((prev) => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Action bar: filters + repo-wide fix / PR actions. Repo-wide analyze
          stays the header's "Run analysis" button. */}
      <div className="flex items-center gap-3 flex-wrap">
        <Button
          variant={unfixed ? "default" : "outline"}
          size="sm"
          onClick={() => {
            setUnfixed((v) => !v)
            setDeselectedPaths(new Set())
          }}
        >
          Open only
        </Button>
        <Button
          variant={showIgnored ? "default" : "outline"}
          size="sm"
          onClick={() => {
            setShowIgnored((v) => !v)
            setDeselectedPaths(new Set())
          }}
        >
          Show ignored
        </Button>
        {selectablePaths.length > 0 && (
          <>
            <Button
              variant="ghost"
              size="sm"
              className="text-xs"
              onClick={() =>
                setDeselectedPaths(
                  allSelected ? new Set(selectablePaths) : new Set(),
                )
              }
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
                : `Fix selected${
                    selectedPaths.length > 0 ? ` (${selectedPaths.length})` : ""
                  }`}
            </Button>
          </>
        )}
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
        {fixes?.some((f) => f.status === "ready") && (
          <Button
            variant="outline"
            size="sm"
            className="gap-2"
            onClick={() =>
              deliverRepoMutation.mutate({ force: repoDeliverAction.force })
            }
            disabled={!isAccessible || deliverRepoMutation.isPending}
          >
            <GitPullRequest className="h-4 w-4" />
            {deliverRepoMutation.isPending
              ? "Queuing…"
              : repoDeliverAction.label}
          </Button>
        )}
      </div>

      {/* Collapsible analysis history */}
      <Card>
        <button
          type="button"
          onClick={() => setHistoryOpen((o) => !o)}
          className="flex w-full items-center gap-2 px-6 py-3 text-left hover:bg-muted/40 transition-colors"
        >
          {historyOpen ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-4 w-4 text-muted-foreground" />
          )}
          <span className="text-sm font-medium">Analysis history</span>
          <span className="text-xs text-muted-foreground">
            ({analyses?.length ?? 0})
          </span>
        </button>
        {historyOpen && (
          <CardContent className="p-0 border-t">
            {!analyses?.length ? (
              <p className="text-sm text-muted-foreground p-6 text-center">
                No analyses found{branch ? ` for branch "${branch}"` : ""}.
              </p>
            ) : (
              <>
                <div className="overflow-x-auto">
                  <div className="grid grid-cols-[1fr_12rem_10rem_7rem_5rem_9rem] min-w-[44rem] items-center px-6 py-2 border-b text-xs font-medium text-muted-foreground uppercase tracking-wide gap-4">
                    <span>Branch</span>
                    <span>Workflow</span>
                    <span>Triggered by</span>
                    <span className="text-center">Status</span>
                    <span className="text-center">Grade</span>
                    <span className="text-right">Date</span>
                  </div>
                  <div className="divide-y">
                    {pagedAnalyses.map((a) => (
                      <Link
                        key={a.id}
                        to="/analyses/$analysisId"
                        params={{ analysisId: a.id }}
                        className="grid grid-cols-[1fr_12rem_10rem_7rem_5rem_9rem] min-w-[44rem] items-center px-6 py-3 gap-4 hover:bg-muted/40 transition-colors"
                      >
                        <span className="text-xs font-mono truncate">
                          {a.branch ?? "—"}
                        </span>
                        <span className="text-xs font-mono text-muted-foreground truncate">
                          {a.workflow_file_path
                            ? a.workflow_file_path.split("/").pop()
                            : "—"}
                        </span>
                        <span className="text-xs text-muted-foreground capitalize">
                          {a.triggered_by.replace(/_/g, " ")}
                        </span>
                        <div className="flex justify-center">
                          <StatusPill
                            colorClass={analysisStatusColor(a.status)}
                          >
                            {analysisStatusLabel(a.status)}
                          </StatusPill>
                        </div>
                        <div className="flex justify-center">
                          <GradeBadge grade={a.grade ?? null} />
                        </div>
                        <span className="text-xs text-muted-foreground tabular-nums whitespace-nowrap text-right">
                          {a.created_at
                            ? new Date(a.created_at).toLocaleDateString(
                                undefined,
                                {
                                  month: "short",
                                  day: "numeric",
                                  hour: "2-digit",
                                  minute: "2-digit",
                                },
                              )
                            : "—"}
                        </span>
                      </Link>
                    ))}
                  </div>
                </div>
                {sortedAnalyses.length > PAGE_SIZE && (
                  <div className="flex items-center justify-between px-6 py-3 border-t">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={historyPage === 0}
                      onClick={() => setHistoryPage((p) => p - 1)}
                    >
                      Previous
                    </Button>
                    <span className="text-xs text-muted-foreground">
                      Page {historyPage + 1} of{" "}
                      {Math.ceil(sortedAnalyses.length / PAGE_SIZE)}
                    </span>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={
                        (historyPage + 1) * PAGE_SIZE >= sortedAnalyses.length
                      }
                      onClick={() => setHistoryPage((p) => p + 1)}
                    >
                      Next
                    </Button>
                  </div>
                )}
              </>
            )}
          </CardContent>
        )}
      </Card>

      {/* Per-workflow cards */}
      {wfLoading ? (
        <div className="flex flex-col gap-4">
          {[...Array(2)].map((_, i) => (
            <Skeleton key={i} className="h-48 w-full" />
          ))}
        </div>
      ) : !sortedWorkflowFiles.length ? (
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground text-sm">
            No workflow files found{branch ? ` for branch "${branch}"` : ""}.
            Run an analysis first.
          </CardContent>
        </Card>
      ) : (
        sortedWorkflowFiles.map((wf) => {
          const fileIssues = issuesByPath.get(wf.path) ?? []
          const fileFix = fixByPath.get(wf.path)
          const latest = latestAnalysisByPath.get(wf.path)
          const showFix =
            fileFix?.status === "ready" || fileFix?.status === "delivered"
          const wfFixInFlight =
            !!fileFix && IN_FLIGHT_STATUSES.includes(fileFix.status)
          const isRegenerating =
            regenerateWorkflowMutation.isPending &&
            regenerateWorkflowMutation.variables === fileFix?.id
          const delivery = fileFix ? deliverAction(fileFix, prByBranch) : null
          const isWfDelivering =
            deliverWorkflowMutation.isPending &&
            deliverWorkflowMutation.variables?.fixId === fileFix?.id
          const selectable = selectablePaths.includes(wf.path)
          const issueListOpen = !collapsedIssueLists.has(wf.path)

          return (
            <Card key={wf.id}>
              <CardHeader className="pb-2 pt-4">
                <div className="flex items-center justify-between gap-4 min-w-0">
                  <CardTitle className="text-sm font-mono flex items-center gap-2 min-w-0 flex-1">
                    {selectable && (
                      <Checkbox
                        checked={!deselectedPaths.has(wf.path)}
                        onCheckedChange={() => toggleWorkflow(wf.path)}
                        className="shrink-0"
                      />
                    )}
                    <span className="truncate min-w-0 flex-1">
                      {workflowLabel(wf.path)}
                    </span>
                    {fileIssues.length > 0 && (
                      <span className="text-muted-foreground font-sans font-normal text-xs shrink-0">
                        ({fileIssues.length} issue
                        {fileIssues.length !== 1 ? "s" : ""})
                      </span>
                    )}
                    {latest && (
                      <StatusPill
                        colorClass={analysisStatusColor(latest.status)}
                        className="shrink-0 font-sans"
                      >
                        {analysisStatusLabel(latest.status)}
                      </StatusPill>
                    )}
                    <GradeBadge
                      grade={latest?.grade ?? null}
                      className="shrink-0"
                    />
                  </CardTitle>
                  <div className="flex items-center gap-2 shrink-0">
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-7 text-xs gap-1.5"
                      onClick={() => analyzeWorkflowMutation.mutate(wf.id)}
                      disabled={
                        !isAccessible ||
                        (analyzeWorkflowMutation.isPending &&
                          analyzeWorkflowMutation.variables === wf.id)
                      }
                      title="Re-run static analysis for this workflow file"
                    >
                      {analyzeWorkflowMutation.isPending &&
                      analyzeWorkflowMutation.variables === wf.id ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Play className="h-3 w-3" />
                      )}
                      Re-analyze
                    </Button>
                    {fileFix && isRegenerable(fileFix) ? (
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 text-xs gap-1.5"
                        onClick={() =>
                          regenerateWorkflowMutation.mutate(fileFix.id)
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
                      fileIssues.some((i) => i.status !== "ignored") && (
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-7 text-xs gap-1.5"
                          onClick={() =>
                            wfFixMutation.mutate({
                              issueIds: fileIssues
                                .filter((i) => i.status !== "ignored")
                                .map((i) => i.id),
                            })
                          }
                          disabled={
                            !isAccessible ||
                            wfFixInFlight ||
                            wfFixMutation.isPending
                          }
                        >
                          {wfFixInFlight || wfFixMutation.isPending ? (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          ) : (
                            <Wand2 className="h-3 w-3" />
                          )}
                          {wfFixInFlight ? "Generating…" : "Generate fix"}
                        </Button>
                      )
                    )}
                    {delivery && (
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 text-xs gap-1.5"
                        onClick={() =>
                          deliverWorkflowMutation.mutate({
                            fixId: fileFix!.id,
                            force: delivery.force,
                          })
                        }
                        disabled={!isAccessible || isWfDelivering}
                      >
                        <GitPullRequest className="h-3 w-3" />
                        {isWfDelivering ? "Queuing…" : delivery.label}
                      </Button>
                    )}
                  </div>
                </div>
              </CardHeader>
              <CardContent className="flex flex-col gap-3">
                <WorkflowFileViewer
                  path={wf.path}
                  rawContent={wf.raw_content ?? ""}
                  fullContent={
                    showFix ? (fileFix?.full_content ?? undefined) : undefined
                  }
                  issues={fileIssues}
                  fix={fileFix}
                />

                {fileIssues.length > 0 && (
                  <div className="rounded-md border">
                    <button
                      type="button"
                      onClick={() => toggleIssueList(wf.path)}
                      className="flex w-full items-center gap-2 px-4 py-2 text-left text-xs font-medium text-muted-foreground hover:bg-muted/40 transition-colors"
                    >
                      {issueListOpen ? (
                        <ChevronDown className="h-3.5 w-3.5" />
                      ) : (
                        <ChevronRight className="h-3.5 w-3.5" />
                      )}
                      Manage {fileIssues.length} issue
                      {fileIssues.length !== 1 ? "s" : ""}
                    </button>
                    {issueListOpen && (
                      <div className="divide-y border-t">
                        {fileIssues.map((issue) => (
                          <IssueRow
                            key={issue.id}
                            issue={issue}
                            repoId={repoId}
                            isAccessible={isAccessible}
                          />
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {fileFix && (
                  <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
                    <div className="flex items-center gap-2 min-w-0">
                      <StatusPill
                        colorClass={fixStatusColor(fileFix.status)}
                        className="capitalize shrink-0"
                      >
                        {fileFix.status}
                      </StatusPill>
                      <span className="truncate">{fileFix.llm_model}</span>
                    </div>
                    {fileFix.pr_url && (
                      <a
                        href={fileFix.pr_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-blue-600 dark:text-blue-400 hover:underline flex items-center gap-1 shrink-0"
                      >
                        <GitPullRequest className="h-3 w-3" />
                        View PR
                        {fileFix.pr_state === "closed" && (
                          <span className="text-orange-500 dark:text-orange-400">
                            (closed)
                          </span>
                        )}
                        {fileFix.pr_state === "merged" && (
                          <span className="text-purple-500 dark:text-purple-400">
                            (merged)
                          </span>
                        )}
                      </a>
                    )}
                  </div>
                )}
              </CardContent>
            </Card>
          )
        })
      )}
    </div>
  )
}
