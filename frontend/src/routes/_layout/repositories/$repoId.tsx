import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { html as diff2htmlString } from "diff2html"
import "diff2html/bundles/css/diff2html.min.css"
import { ColorSchemeType } from "diff2html/lib/types"
import {
  ArrowLeft,
  GitBranch,
  GitPullRequest,
  Play,
  Puzzle,
  Zap,
} from "lucide-react"
import { useMemo, useState } from "react"
import { toast } from "sonner"
import type { FixPublic, IssuePublic } from "@/client"
import {
  AnalysesService,
  ApiError,
  FixesService,
  IssuesService,
  RepositoriesService,
} from "@/client"
import { CategoryIcon } from "@/components/CategoryIcon"
import { GradeBadge } from "@/components/GradeBadge"
import { IssueRow } from "@/components/IssueRow"
import { SeverityChip } from "@/components/SeverityChip"
import { useTheme } from "@/components/theme-provider"
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { analysisStatusColor, fixStatusColor } from "@/lib/status-colors"

type RepoTab = "analyses" | "issues" | "fixes" | "diffs" | "pull-requests"
type RepoDetailSearch = { branch?: string; tab?: RepoTab }

const VALID_TABS: RepoTab[] = [
  "analyses",
  "issues",
  "fixes",
  "diffs",
  "pull-requests",
]

function extractFilePath(patch: string): string {
  const gitMatch = patch.match(/^diff --git a\/(.+?) b\/.+$/m)
  if (gitMatch) return gitMatch[1]
  const unifiedMatch = patch.match(/^--- a\/(.+)$/m)
  return unifiedMatch?.[1] ?? ""
}

function combinePatchesForFile(patches: string[]): string {
  if (patches.length === 0) return ""
  const unique = [...new Set(patches)]
  if (unique.length === 1) return unique[0]
  const hunkStart = unique[0].indexOf("@@")
  const header = hunkStart !== -1 ? unique[0].slice(0, hunkStart) : unique[0]
  const hunks = unique
    .map((p) => {
      const start = p.indexOf("@@")
      return start !== -1 ? p.slice(start) : ""
    })
    .filter(Boolean)
    .join("\n")
  return header + hunks
}

export const Route = createFileRoute("/_layout/repositories/$repoId")({
  component: RepositoryDetail,
  validateSearch: (search: Record<string, unknown>): RepoDetailSearch => ({
    branch: typeof search.branch === "string" ? search.branch : undefined,
    tab: VALID_TABS.includes(search.tab as RepoTab)
      ? (search.tab as RepoTab)
      : undefined,
  }),
  head: () => ({
    meta: [{ title: "Repository - GreenSecOps" }],
  }),
})

function workflowLabel(path: string): string {
  if (!path) return "Unknown workflow"
  return path.split("/").pop() ?? path
}

function groupByWorkflowFile(
  issues: IssuePublic[],
): Map<string, IssuePublic[]> {
  const groups = new Map<string, IssuePublic[]>()
  for (const issue of issues) {
    const key = issue.workflow_file_path ?? ""
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(issue)
  }
  return groups
}

function RepositoryDetail() {
  const { repoId } = Route.useParams()
  const { branch, tab } = Route.useSearch()
  const navigate = Route.useNavigate()
  const queryClient = useQueryClient()
  const { resolvedTheme } = useTheme()
  const [unfixed, setUnfixed] = useState(false)
  const [deselectedIds, setDeselectedIds] = useState<Set<string>>(new Set())
  const [prStateFilter, setPrStateFilter] = useState<string>("all")
  const [prPage, setPrPage] = useState(0)
  const [analysesPage, setAnalysesPage] = useState(0)
  const [issuesPage, setIssuesPage] = useState(0)
  const [fixesPage, setFixesPage] = useState(0)
  const [diffsPage, setDiffsPage] = useState(0)
  const PAGE_SIZE = 20

  const { data: repo, isLoading: repoLoading } = useQuery({
    queryKey: ["repository", repoId],
    queryFn: () => RepositoriesService.getRepository({ repoId }),
  })

  const currentGrade = repo?.grade ?? null

  const { data: analyses, isLoading: analysesLoading } = useQuery({
    queryKey: ["analyses", repoId, branch],
    queryFn: () =>
      AnalysesService.listAnalyses({
        repoId,
        branch: branch || undefined,
        limit: 100,
      }),
  })

  const { data: issues, isLoading: issuesLoading } = useQuery({
    queryKey: ["issues", "repo", repoId, { unfixed }],
    queryFn: () =>
      IssuesService.listIssues({
        repoId,
        unfixed: unfixed || undefined,
        limit: 200,
      }),
  })

  const { data: fixes, isLoading: fixesLoading } = useQuery({
    queryKey: ["fixes", "repo", repoId],
    queryFn: () => FixesService.listFixes({ repoId, limit: 100 }),
  })

  const { data: allIssues } = useQuery({
    queryKey: ["issues", "repo", repoId, { unfixed: false }],
    queryFn: () => IssuesService.listIssues({ repoId, limit: 200 }),
  })

  const triggerMutation = useMutation({
    mutationFn: () => AnalysesService.triggerAnalysis({ repoId }),
    onSuccess: () => {
      toast.success("Analysis queued")
      queryClient.invalidateQueries({ queryKey: ["analyses", repoId] })
    },
    onError: () => toast.error("Failed to trigger analysis"),
  })

  const integrateActionMutation = useMutation({
    mutationFn: () => RepositoriesService.integrateAction({ repoId }),
    onSuccess: (data) => {
      toast.success("PR opened", {
        description: data.pr_url,
        action: data.pr_url
          ? {
              label: "Open",
              onClick: () => window.open(data.pr_url, "_blank"),
            }
          : undefined,
      })
    },
    onError: (error) => {
      const detail =
        error instanceof ApiError
          ? (error.body as { detail?: string })?.detail
          : undefined
      toast.error("Failed to integrate action", {
        description: detail,
      })
    },
  })

  const selectedIds = useMemo(() => {
    if (!issues) return []
    return issues.filter((i) => !deselectedIds.has(i.id)).map((i) => i.id)
  }, [issues, deselectedIds])

  const batchFixMutation = useMutation({
    mutationFn: () =>
      FixesService.triggerFixGenerationForRepo({
        repoId,
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
    onError: () => toast.error("Failed to queue fixes"),
  })

  const deliverWorkflowMutation = useMutation({
    mutationFn: (fixIds: string[]) =>
      FixesService.triggerWorkflowDelivery({
        requestBody: { fix_ids: fixIds },
      }),
    onSuccess: () => {
      toast.success("Workflow PR queued")
      queryClient.invalidateQueries({ queryKey: ["fixes", "repo", repoId] })
    },
    onError: () => toast.error("Failed to queue workflow PR"),
  })

  const deliverRepoMutation = useMutation({
    mutationFn: () => FixesService.triggerRepoDelivery({ repoId }),
    onSuccess: () => {
      toast.success("Repo-wide PR queued")
      queryClient.invalidateQueries({ queryKey: ["fixes", "repo", repoId] })
    },
    onError: () => toast.error("Failed to queue repo-wide PR"),
  })

  const branches = analyses
    ? [...new Set(analyses.map((a) => a.branch).filter(Boolean) as string[])]
    : []

  const issueById = useMemo(() => {
    const map = new Map<string, IssuePublic>()
    for (const issue of allIssues ?? []) map.set(issue.id, issue)
    return map
  }, [allIssues])

  const fixesByWorkflow = useMemo(() => {
    if (!fixes) return null
    const groups = new Map<string, typeof fixes>()
    for (const fix of fixes) {
      const issue = issueById.get(fix.issue_id)
      const key = issue?.workflow_file_path ?? ""
      if (!groups.has(key)) groups.set(key, [])
      groups.get(key)!.push(fix)
    }
    return groups
  }, [fixes, issueById])

  const allGsPrs = useMemo(() => {
    if (!fixes) return []
    const seen = new Set<string>()
    return fixes
      .filter((f) => f.pr_url)
      .filter((f) => {
        if (seen.has(f.pr_url!)) return false
        seen.add(f.pr_url!)
        return true
      })
      .sort(
        (a, b) =>
          new Date(b.created_at ?? 0).getTime() -
          new Date(a.created_at ?? 0).getTime(),
      )
  }, [fixes])

  const filteredGsPrs = useMemo(() => {
    if (prStateFilter === "all") return allGsPrs
    return allGsPrs.filter((f) => (f.pr_state ?? "open") === prStateFilter)
  }, [allGsPrs, prStateFilter])

  const pagedGsPrs = useMemo(
    () => filteredGsPrs.slice(prPage * PAGE_SIZE, (prPage + 1) * PAGE_SIZE),
    [filteredGsPrs, prPage],
  )

  const pagedAnalyses = useMemo(
    () =>
      (analyses ?? []).slice(
        analysesPage * PAGE_SIZE,
        (analysesPage + 1) * PAGE_SIZE,
      ),
    [analyses, analysesPage],
  )

  const pagedIssues = useMemo(
    () =>
      (issues ?? []).slice(
        issuesPage * PAGE_SIZE,
        (issuesPage + 1) * PAGE_SIZE,
      ),
    [issues, issuesPage],
  )

  const pagedIssuesByWorkflow = useMemo(
    () => groupByWorkflowFile(pagedIssues),
    [pagedIssues],
  )

  const pagedFixes = useMemo(
    () =>
      (fixes ?? []).slice(fixesPage * PAGE_SIZE, (fixesPage + 1) * PAGE_SIZE),
    [fixes, fixesPage],
  )

  const pagedFixesByWorkflow = useMemo(() => {
    const groups = new Map<string, FixPublic[]>()
    for (const fix of pagedFixes) {
      const issue = issueById.get(fix.issue_id)
      const key = issue?.workflow_file_path ?? ""
      if (!groups.has(key)) groups.set(key, [])
      groups.get(key)!.push(fix)
    }
    return groups
  }, [pagedFixes, issueById])

  const readyFixes = useMemo(
    () => (fixes ?? []).filter((f) => f.status === "ready"),
    [fixes],
  )

  const pagedReadyFixes = useMemo(
    () => readyFixes.slice(diffsPage * PAGE_SIZE, (diffsPage + 1) * PAGE_SIZE),
    [readyFixes, diffsPage],
  )

  const pagedReadyFixesByWorkflow = useMemo(() => {
    const groups = new Map<string, FixPublic[]>()
    for (const fix of pagedReadyFixes) {
      const issue = issueById.get(fix.issue_id)
      const key = issue?.workflow_file_path ?? ""
      if (!groups.has(key)) groups.set(key, [])
      groups.get(key)!.push(fix)
    }
    return groups
  }, [pagedReadyFixes, issueById])

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
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <Link
            to="/repositories"
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <div>
            <div className="flex items-center gap-3">
              {repoLoading ? (
                <Skeleton className="h-7 w-64" />
              ) : (
                <h1 className="text-2xl font-bold tracking-tight font-mono">
                  {repo?.full_name}
                </h1>
              )}
              <GradeBadge grade={currentGrade} />
            </div>
            {repo && (
              <span className="inline-flex items-center gap-1 text-xs text-muted-foreground mt-0.5">
                <GitBranch className="h-3 w-3" />
                default: {repo.default_branch}
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            className="gap-2"
            onClick={() => integrateActionMutation.mutate()}
            disabled={
              integrateActionMutation.isPending ||
              integrateActionMutation.isSuccess
            }
          >
            <Puzzle className="h-4 w-4" />
            {integrateActionMutation.isPending
              ? "Opening PR…"
              : integrateActionMutation.isSuccess
                ? "PR opened"
                : "Integrate action"}
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="gap-2"
            onClick={() => triggerMutation.mutate()}
            disabled={triggerMutation.isPending}
          >
            <Play className="h-4 w-4" />
            Run analysis
          </Button>
        </div>
      </div>

      <Tabs
        value={tab ?? "analyses"}
        onValueChange={(t) =>
          navigate({
            search: (prev) => ({ ...prev, tab: t as RepoTab }),
          })
        }
      >
        <TabsList className="w-full overflow-x-auto justify-start">
          <TabsTrigger value="analyses">Analyses</TabsTrigger>
          <TabsTrigger value="issues">
            Issues
            {issues?.length ? (
              <span className="ml-1.5 text-xs bg-muted px-1.5 py-0.5 rounded-full">
                {issues.length}
              </span>
            ) : null}
          </TabsTrigger>
          <TabsTrigger value="fixes">
            Fixes
            {fixes?.length ? (
              <span className="ml-1.5 text-xs bg-muted px-1.5 py-0.5 rounded-full">
                {fixes.length}
              </span>
            ) : null}
          </TabsTrigger>
          <TabsTrigger value="diffs">
            Diffs
            {fixes?.some((f) => f.status === "ready") ? (
              <span className="ml-1.5 text-xs bg-muted px-1.5 py-0.5 rounded-full">
                {fixes.filter((f) => f.status === "ready").length}
              </span>
            ) : null}
          </TabsTrigger>
          <TabsTrigger value="pull-requests">
            <GitPullRequest className="h-3.5 w-3.5 mr-1" />
            Pull Requests
            {allGsPrs.length > 0 ? (
              <span className="ml-1.5 text-xs bg-muted px-1.5 py-0.5 rounded-full">
                {allGsPrs.length}
              </span>
            ) : null}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="analyses" className="flex flex-col gap-4 mt-4">
          <div className="flex items-center gap-3">
            <p className="text-sm text-muted-foreground">Branch:</p>
            <Select
              value={branch ?? ""}
              onValueChange={(val) =>
                navigate({ search: val ? { branch: val } : {} })
              }
            >
              <SelectTrigger className="w-48 h-8 text-xs">
                <SelectValue placeholder="All branches" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="">All branches</SelectItem>
                {branches.map((b) => (
                  <SelectItem key={b} value={b}>
                    {b}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {branch && (
              <Button
                variant="ghost"
                size="sm"
                className="h-8 text-xs"
                onClick={() => navigate({ search: {} })}
              >
                Clear
              </Button>
            )}
          </div>

          <Card>
            <CardContent className="p-0">
              {analysesLoading ? (
                <div className="flex flex-col gap-2 p-6">
                  {[...Array(4)].map((_, i) => (
                    <Skeleton key={i} className="h-12 w-full" />
                  ))}
                </div>
              ) : !analyses?.length ? (
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
                          <span
                            className={`text-xs font-medium px-2 py-0.5 rounded-full capitalize ${analysisStatusColor(a.status)}`}
                          >
                            {a.status}
                          </span>
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
                  {(analyses?.length ?? 0) > PAGE_SIZE && (
                    <div className="flex items-center justify-between px-6 py-3 border-t">
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={analysesPage === 0}
                        onClick={() => setAnalysesPage((p) => p - 1)}
                      >
                        Previous
                      </Button>
                      <span className="text-xs text-muted-foreground">
                        Page {analysesPage + 1} of{" "}
                        {Math.ceil((analyses?.length ?? 0) / PAGE_SIZE)}
                      </span>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={
                          (analysesPage + 1) * PAGE_SIZE >=
                          (analyses?.length ?? 0)
                        }
                        onClick={() => setAnalysesPage((p) => p + 1)}
                      >
                        Next
                      </Button>
                    </div>
                  )}
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="issues" className="flex flex-col gap-4 mt-4">
          <div className="flex items-center gap-3 flex-wrap">
            <Button
              variant={unfixed ? "default" : "outline"}
              size="sm"
              onClick={() => {
                setUnfixed((v) => !v)
                setDeselectedIds(new Set())
                setIssuesPage(0)
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
              disabled={
                batchFixMutation.isPending ||
                batchFixMutation.isSuccess ||
                noneSelected
              }
            >
              <Zap className="h-4 w-4" />
              {batchFixMutation.isPending
                ? "Queuing…"
                : batchFixMutation.isSuccess
                  ? "Queued"
                  : `Fix selected${selectedIds.length > 0 ? ` (${selectedIds.length})` : ""}`}
            </Button>
          </div>

          {issuesLoading ? (
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
                    <CardTitle className="text-sm font-mono flex items-center gap-2">
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
                      <span className="text-muted-foreground font-sans font-normal text-xs">
                        Workflow:
                      </span>
                      {workflowLabel(wfPath)}
                      <span className="text-muted-foreground font-normal text-xs">
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
                disabled={issuesPage === 0}
                onClick={() => setIssuesPage((p) => p - 1)}
              >
                Previous
              </Button>
              <span className="text-xs text-muted-foreground">
                Page {issuesPage + 1} of{" "}
                {Math.ceil((issues?.length ?? 0) / PAGE_SIZE)}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={(issuesPage + 1) * PAGE_SIZE >= (issues?.length ?? 0)}
                onClick={() => setIssuesPage((p) => p + 1)}
              >
                Next
              </Button>
            </div>
          )}
        </TabsContent>

        <TabsContent value="fixes" className="flex flex-col gap-4 mt-4">
          {fixesLoading ? (
            <div className="flex flex-col gap-2">
              {[...Array(4)].map((_, i) => (
                <Skeleton key={i} className="h-14 w-full" />
              ))}
            </div>
          ) : !fixes?.length ? (
            <Card>
              <CardContent className="py-8 text-center text-muted-foreground text-sm">
                No fixes yet.
              </CardContent>
            </Card>
          ) : (
            <>
              {fixes.some((f) => f.status === "ready") && (
                <div className="flex justify-end">
                  <Button
                    size="sm"
                    variant="outline"
                    className="gap-2"
                    onClick={() => deliverRepoMutation.mutate()}
                    disabled={deliverRepoMutation.isPending}
                  >
                    <GitPullRequest className="h-4 w-4" />
                    {deliverRepoMutation.isPending
                      ? "Queuing…"
                      : "Create PR for all workflows"}
                  </Button>
                </div>
              )}
              {[...pagedFixesByWorkflow.entries()].map(([wfPath, wfFixes]) => {
                const allWfReadyFixIds = (fixesByWorkflow?.get(wfPath) ?? [])
                  .filter((f) => f.status === "ready")
                  .map((f) => f.id)
                const isWfDelivering =
                  deliverWorkflowMutation.isPending &&
                  allWfReadyFixIds.some((id) =>
                    deliverWorkflowMutation.variables?.includes(id),
                  )
                return (
                  <Card key={wfPath || "__unknown__"}>
                    <CardHeader className="pb-2 pt-4">
                      <div className="flex items-center justify-between gap-4">
                        <CardTitle className="text-sm font-mono flex items-center gap-2 min-w-0">
                          <span className="text-muted-foreground font-sans font-normal text-xs shrink-0">
                            Workflow:
                          </span>
                          <span className="truncate">
                            {workflowLabel(wfPath)}
                          </span>
                          <span className="text-muted-foreground font-normal text-xs shrink-0">
                            ({wfFixes.length})
                          </span>
                        </CardTitle>
                        {allWfReadyFixIds.length > 0 && (
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-7 text-xs gap-1.5 shrink-0"
                            onClick={() =>
                              deliverWorkflowMutation.mutate(allWfReadyFixIds)
                            }
                            disabled={isWfDelivering}
                          >
                            <GitPullRequest className="h-3 w-3" />
                            {isWfDelivering
                              ? "Queuing…"
                              : `Create PR (${allWfReadyFixIds.length} fix${allWfReadyFixIds.length !== 1 ? "es" : ""})`}
                          </Button>
                        )}
                      </div>
                    </CardHeader>
                    <CardContent className="p-0">
                      <div className="divide-y">
                        {wfFixes.map((fix) => {
                          const issue = issueById.get(fix.issue_id)
                          return (
                            <div
                              key={fix.id}
                              className="flex items-start gap-3 px-6 py-4"
                            >
                              <span
                                className={`mt-0.5 shrink-0 text-xs font-medium px-2 py-0.5 rounded-full capitalize ${fixStatusColor(fix.status)}`}
                              >
                                {fix.status}
                              </span>
                              {issue && (
                                <CategoryIcon
                                  category={issue.category}
                                  className="mt-0.5 shrink-0 text-base"
                                />
                              )}
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2 flex-wrap">
                                  {issue && (
                                    <SeverityChip severity={issue.severity} />
                                  )}
                                  {issue && (
                                    <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-mono bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300">
                                      {issue.rule_slug}
                                    </span>
                                  )}
                                  <span className="text-sm">
                                    {issue?.message ??
                                      `${fix.issue_id.slice(0, 8)}…`}
                                  </span>
                                </div>
                                {issue?.line_start != null && (
                                  <p className="text-xs text-muted-foreground mt-0.5">
                                    Line {issue.line_start}
                                    {issue.line_end &&
                                    issue.line_end !== issue.line_start
                                      ? `–${issue.line_end}`
                                      : ""}
                                  </p>
                                )}
                                <p className="text-xs text-muted-foreground mt-0.5">
                                  {fix.llm_model}
                                </p>
                              </div>
                              <div className="shrink-0 flex flex-col items-end gap-1.5">
                                {fix.pr_url ? (
                                  <a
                                    href={fix.pr_url}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="text-xs text-blue-600 dark:text-blue-400 hover:underline flex items-center gap-1"
                                  >
                                    <GitPullRequest className="h-3 w-3" />
                                    View PR
                                  </a>
                                ) : fix.comment_url ? (
                                  <a
                                    href={fix.comment_url}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="text-xs text-blue-600 dark:text-blue-400 hover:underline"
                                  >
                                    Comment
                                  </a>
                                ) : null}
                                <span className="text-xs text-muted-foreground tabular-nums whitespace-nowrap">
                                  {fix.created_at
                                    ? new Date(
                                        fix.created_at,
                                      ).toLocaleDateString(undefined, {
                                        month: "short",
                                        day: "numeric",
                                      })
                                    : "—"}
                                </span>
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    </CardContent>
                  </Card>
                )
              })}
              {(fixes?.length ?? 0) > PAGE_SIZE && (
                <div className="flex items-center justify-between py-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={fixesPage === 0}
                    onClick={() => setFixesPage((p) => p - 1)}
                  >
                    Previous
                  </Button>
                  <span className="text-xs text-muted-foreground">
                    Page {fixesPage + 1} of{" "}
                    {Math.ceil((fixes?.length ?? 0) / PAGE_SIZE)}
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={
                      (fixesPage + 1) * PAGE_SIZE >= (fixes?.length ?? 0)
                    }
                    onClick={() => setFixesPage((p) => p + 1)}
                  >
                    Next
                  </Button>
                </div>
              )}
            </>
          )}
        </TabsContent>

        <TabsContent value="diffs" className="flex flex-col gap-4 mt-4">
          {fixesLoading ? (
            <div className="flex flex-col gap-2">
              {[...Array(4)].map((_, i) => (
                <Skeleton key={i} className="h-14 w-full" />
              ))}
            </div>
          ) : !fixes?.some((f) => f.status === "ready") ? (
            <Card>
              <CardContent className="py-8 text-center text-muted-foreground text-sm">
                No ready fixes to preview. Generate fixes first.
              </CardContent>
            </Card>
          ) : (
            <>
              {[...pagedReadyFixesByWorkflow.entries()].map(
                ([wfPath, wfFixes]) => {
                  const allWfReadyFixIds = (fixesByWorkflow?.get(wfPath) ?? [])
                    .filter((f) => f.status === "ready")
                    .map((f) => f.id)
                  const isWfDelivering =
                    deliverWorkflowMutation.isPending &&
                    allWfReadyFixIds.some((id) =>
                      deliverWorkflowMutation.variables?.includes(id),
                    )

                  const fileGroups = new Map<
                    string,
                    { fixes: FixPublic[]; patch: string }
                  >()
                  for (const fix of wfFixes) {
                    if (!fix.diff_patch) continue
                    const filePath = extractFilePath(fix.diff_patch) || fix.id
                    if (!fileGroups.has(filePath))
                      fileGroups.set(filePath, { fixes: [], patch: "" })
                    fileGroups.get(filePath)!.fixes.push(fix)
                  }
                  for (const entry of fileGroups.values()) {
                    const patches = entry.fixes
                      .map((f) => f.diff_patch)
                      .filter(Boolean) as string[]
                    entry.patch = combinePatchesForFile(patches)
                  }

                  return (
                    <Card key={wfPath || "__unknown__"}>
                      <CardHeader className="pb-2 pt-4">
                        <div className="flex items-center justify-between gap-4">
                          <CardTitle className="text-sm font-mono flex items-center gap-2 min-w-0">
                            <span className="text-muted-foreground font-sans font-normal text-xs shrink-0">
                              Workflow:
                            </span>
                            <span className="truncate">
                              {workflowLabel(wfPath)}
                            </span>
                            <span className="text-muted-foreground font-normal text-xs shrink-0">
                              ({allWfReadyFixIds.length})
                            </span>
                          </CardTitle>
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-7 text-xs gap-1.5 shrink-0"
                            onClick={() =>
                              deliverWorkflowMutation.mutate(allWfReadyFixIds)
                            }
                            disabled={isWfDelivering}
                          >
                            <GitPullRequest className="h-3 w-3" />
                            {isWfDelivering
                              ? "Queuing…"
                              : `Create PR (${allWfReadyFixIds.length} fix${allWfReadyFixIds.length !== 1 ? "es" : ""})`}
                          </Button>
                        </div>
                      </CardHeader>
                      <CardContent className="p-0">
                        {[...fileGroups.values()].map((group, i) => {
                          const diffHtml = group.patch
                            ? diff2htmlString(group.patch, {
                                drawFileList: false,
                                matching: "lines",
                                outputFormat: "line-by-line",
                                colorScheme:
                                  resolvedTheme === "dark"
                                    ? ColorSchemeType.DARK
                                    : ColorSchemeType.LIGHT,
                              })
                            : null
                          return (
                            <div key={i} className="border-t">
                              {group.fixes.map((fix) => {
                                const issue = issueById.get(fix.issue_id)
                                return issue ? (
                                  <div
                                    key={fix.id}
                                    className="flex items-center gap-2 px-6 py-2 flex-wrap"
                                  >
                                    <SeverityChip severity={issue.severity} />
                                    <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-mono bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300">
                                      {issue.rule_slug}
                                    </span>
                                    <span className="text-sm">
                                      {issue.message}
                                    </span>
                                  </div>
                                ) : null
                              })}
                              {diffHtml ? (
                                <div
                                  className="diff2html-wrapper text-xs overflow-x-auto"
                                  // biome-ignore lint/security/noDangerouslySetInnerHtml: diff2html renders structured patch data from the API, not raw user input
                                  dangerouslySetInnerHTML={{ __html: diffHtml }}
                                />
                              ) : (
                                <p className="text-xs text-muted-foreground px-6 py-2">
                                  No diff available.
                                </p>
                              )}
                            </div>
                          )
                        })}
                      </CardContent>
                    </Card>
                  )
                },
              )}
              {readyFixes.length > PAGE_SIZE && (
                <div className="flex items-center justify-between py-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={diffsPage === 0}
                    onClick={() => setDiffsPage((p) => p - 1)}
                  >
                    Previous
                  </Button>
                  <span className="text-xs text-muted-foreground">
                    Page {diffsPage + 1} of{" "}
                    {Math.ceil(readyFixes.length / PAGE_SIZE)}
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={(diffsPage + 1) * PAGE_SIZE >= readyFixes.length}
                    onClick={() => setDiffsPage((p) => p + 1)}
                  >
                    Next
                  </Button>
                </div>
              )}
            </>
          )}
        </TabsContent>

        <TabsContent value="pull-requests" className="flex flex-col gap-4 mt-4">
          <div className="flex items-center justify-between gap-4">
            <Select
              value={prStateFilter}
              onValueChange={(v) => {
                setPrStateFilter(v)
                setPrPage(0)
              }}
            >
              <SelectTrigger className="w-36 h-8 text-xs">
                <SelectValue placeholder="Filter by state" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All</SelectItem>
                <SelectItem value="open">Open</SelectItem>
                <SelectItem value="closed">Closed</SelectItem>
                <SelectItem value="merged">Merged</SelectItem>
              </SelectContent>
            </Select>
            <span className="text-xs text-muted-foreground">
              {filteredGsPrs.length} PR{filteredGsPrs.length !== 1 ? "s" : ""}
            </span>
          </div>
          <Card>
            <CardContent className="p-0">
              {fixesLoading ? (
                <div className="flex flex-col gap-2 p-6">
                  {[...Array(4)].map((_, i) => (
                    <Skeleton key={i} className="h-12 w-full" />
                  ))}
                </div>
              ) : filteredGsPrs.length === 0 ? (
                <p className="text-sm text-muted-foreground p-6 text-center">
                  {prStateFilter === "all"
                    ? "No GreenSecOps-created PRs yet. Generate and deliver fixes to see them here."
                    : `No ${prStateFilter} PRs.`}
                </p>
              ) : (
                <>
                  <div className="grid grid-cols-[1fr_6rem_8rem] items-center px-4 sm:px-6 py-2 border-b text-xs font-medium text-muted-foreground uppercase tracking-wide gap-4">
                    <span>Pull Request</span>
                    <span className="text-center">State</span>
                    <span className="text-right">Date</span>
                  </div>
                  <div className="divide-y">
                    {pagedGsPrs.map((fix) => {
                      const state = fix.pr_state ?? "open"
                      const stateCls =
                        state === "merged"
                          ? "bg-purple-500/15 text-purple-700 dark:text-purple-400"
                          : state === "closed"
                            ? "bg-red-500/15 text-red-700 dark:text-red-400"
                            : "bg-green-500/15 text-green-700 dark:text-green-400"
                      return (
                        <div
                          key={fix.pr_url}
                          className="grid grid-cols-[1fr_6rem_8rem] items-center px-4 sm:px-6 py-3 gap-4"
                        >
                          <a
                            href={fix.pr_url!}
                            target="_blank"
                            rel="noreferrer"
                            className="text-xs font-mono text-blue-600 dark:text-blue-400 hover:underline truncate flex items-center gap-1.5"
                          >
                            <GitPullRequest className="h-3 w-3 shrink-0" />
                            {fix.pr_url!.replace("https://github.com/", "")}
                          </a>
                          <span
                            className={`text-xs font-medium px-2 py-0.5 rounded-full capitalize text-center ${stateCls}`}
                          >
                            {state}
                          </span>
                          <span className="text-xs text-muted-foreground tabular-nums whitespace-nowrap text-right">
                            {fix.delivered_at
                              ? new Date(fix.delivered_at).toLocaleDateString(
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
                        </div>
                      )
                    })}
                  </div>
                  {filteredGsPrs.length > PAGE_SIZE && (
                    <div className="flex items-center justify-between px-6 py-3 border-t">
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={prPage === 0}
                        onClick={() => setPrPage((p) => p - 1)}
                      >
                        Previous
                      </Button>
                      <span className="text-xs text-muted-foreground">
                        Page {prPage + 1} of{" "}
                        {Math.ceil(filteredGsPrs.length / PAGE_SIZE)}
                      </span>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={
                          (prPage + 1) * PAGE_SIZE >= filteredGsPrs.length
                        }
                        onClick={() => setPrPage((p) => p + 1)}
                      >
                        Next
                      </Button>
                    </div>
                  )}
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}
