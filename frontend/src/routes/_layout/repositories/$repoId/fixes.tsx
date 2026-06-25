import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { html as diff2htmlString } from "diff2html"
import "diff2html/bundles/css/diff2html.min.css"
import { ColorSchemeType } from "diff2html/lib/types"
import { GitPullRequest } from "lucide-react"
import { useMemo, useState } from "react"
import { toast } from "sonner"
import type { FixPublic, IssuePublic } from "@/client"
import { FixesService, IssuesService } from "@/client"
import { CategoryIcon } from "@/components/CategoryIcon"
import { SeverityChip } from "@/components/SeverityChip"
import { useTheme } from "@/components/theme-provider"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { fixStatusColor } from "@/lib/status-colors"
import {
  combinePatchesForFile,
  extractFilePath,
  groupFixesByWorkflow,
  PAGE_SIZE,
  workflowLabel,
} from "@/lib/workflow-utils"

export const Route = createFileRoute("/_layout/repositories/$repoId/fixes")({
  component: FixesPage,
  head: () => ({
    meta: [{ title: "Fixes - GreenSecOps" }],
  }),
})

function FixesPage() {
  const { repoId } = Route.useParams()
  const queryClient = useQueryClient()
  const { resolvedTheme } = useTheme()
  const [fixesPage, setFixesPage] = useState(0)
  const [diffsPage, setDiffsPage] = useState(0)
  const [view, setView] = useState<"list" | "diffs">("list")

  const { data: fixes, isLoading: fixesLoading } = useQuery({
    queryKey: ["fixes", "repo", repoId],
    queryFn: () => FixesService.listFixes({ repoId, limit: 100 }),
  })

  const { data: allIssues } = useQuery({
    queryKey: ["issues", "repo", repoId, { unfixed: false }],
    queryFn: () => IssuesService.listIssues({ repoId, limit: 200 }),
  })

  const issueById = useMemo(() => {
    const map = new Map<string, IssuePublic>()
    for (const issue of allIssues ?? []) map.set(issue.id, issue)
    return map
  }, [allIssues])

  const fixesByWorkflow = useMemo(
    () => (fixes ? groupFixesByWorkflow(fixes, issueById) : null),
    [fixes, issueById],
  )

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

  const pagedFixes = useMemo(
    () =>
      (fixes ?? []).slice(fixesPage * PAGE_SIZE, (fixesPage + 1) * PAGE_SIZE),
    [fixes, fixesPage],
  )

  const pagedFixesByWorkflow = useMemo(
    () => groupFixesByWorkflow(pagedFixes, issueById),
    [pagedFixes, issueById],
  )

  const readyFixes = useMemo(
    () => (fixes ?? []).filter((f) => f.status === "ready"),
    [fixes],
  )

  const pagedReadyFixes = useMemo(
    () => readyFixes.slice(diffsPage * PAGE_SIZE, (diffsPage + 1) * PAGE_SIZE),
    [readyFixes, diffsPage],
  )

  const pagedReadyFixesByWorkflow = useMemo(
    () => groupFixesByWorkflow(pagedReadyFixes, issueById),
    [pagedReadyFixes, issueById],
  )

  return (
    <div className="flex flex-col gap-4">
      <Tabs value={view} onValueChange={(v) => setView(v as "list" | "diffs")}>
        <div className="flex items-center justify-between gap-4">
          <TabsList>
            <TabsTrigger value="list">
              Fixes
              {fixes?.length ? (
                <span className="ml-1.5 text-xs bg-muted px-1.5 py-0.5 rounded-full">
                  {fixes.length}
                </span>
              ) : null}
            </TabsTrigger>
            <TabsTrigger value="diffs">
              Diffs
              {readyFixes.length > 0 ? (
                <span className="ml-1.5 text-xs bg-muted px-1.5 py-0.5 rounded-full">
                  {readyFixes.length}
                </span>
              ) : null}
            </TabsTrigger>
          </TabsList>
          {fixes?.some((f) => f.status === "ready") && (
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
                : fixes.some((f) => f.pr_url)
                  ? "Update PR for all workflows"
                  : "Create PR for all workflows"}
            </Button>
          )}
        </div>

        <TabsContent value="list" className="flex flex-col gap-4 mt-4">
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
              {[...pagedFixesByWorkflow.entries()].map(([wfPath, wfFixes]) => {
                const allWfFixes = fixesByWorkflow?.get(wfPath) ?? []
                const allWfReadyFixIds = allWfFixes
                  .filter((f) => f.status === "ready")
                  .map((f) => f.id)
                const hasExistingPr = allWfFixes.some((f) => f.pr_url)
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
                              : `${hasExistingPr ? "Update" : "Create"} PR (${allWfReadyFixIds.length} fix${allWfReadyFixIds.length !== 1 ? "es" : ""})`}
                          </Button>
                        )}
                      </div>
                    </CardHeader>
                    <CardContent className="p-0">
                      <div className="divide-y">
                        {wfFixes.map((fix) => {
                          const issue = issueById.get(fix.issue_id)
                          const severity = fix.severity ?? issue?.severity
                          const category = fix.category ?? issue?.category
                          const ruleSlug = fix.rule_slug ?? issue?.rule_slug
                          const message =
                            fix.message ??
                            issue?.message ??
                            `${fix.issue_id.slice(0, 8)}…`
                          const lineStart =
                            fix.line_start ?? issue?.line_start
                          const lineEnd = fix.line_end ?? issue?.line_end
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
                              {category && (
                                <CategoryIcon
                                  category={category}
                                  className="mt-0.5 shrink-0 text-base"
                                />
                              )}
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2 flex-wrap">
                                  {severity && (
                                    <SeverityChip severity={severity} />
                                  )}
                                  {ruleSlug && (
                                    <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-mono bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300">
                                      {ruleSlug}
                                    </span>
                                  )}
                                  <span className="text-sm">{message}</span>
                                </div>
                                {lineStart != null && (
                                  <p className="text-xs text-muted-foreground mt-0.5">
                                    Line {lineStart}
                                    {lineEnd && lineEnd !== lineStart
                                      ? `–${lineEnd}`
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
                  const allWfFixes = fixesByWorkflow?.get(wfPath) ?? []
                  const allWfReadyFixIds = allWfFixes
                    .filter((f) => f.status === "ready")
                    .map((f) => f.id)
                  const hasExistingPr = allWfFixes.some((f) => f.pr_url)
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
                              : `${hasExistingPr ? "Update" : "Create"} PR (${allWfReadyFixIds.length} fix${allWfReadyFixIds.length !== 1 ? "es" : ""})`}
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
                                const severity =
                                  fix.severity ?? issue?.severity
                                const ruleSlug =
                                  fix.rule_slug ?? issue?.rule_slug
                                const message =
                                  fix.message ?? issue?.message
                                return severity && ruleSlug && message ? (
                                  <div
                                    key={fix.id}
                                    className="flex items-center gap-2 px-6 py-2 flex-wrap"
                                  >
                                    <SeverityChip severity={severity} />
                                    <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-mono bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300">
                                      {ruleSlug}
                                    </span>
                                    <span className="text-sm">{message}</span>
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
      </Tabs>
    </div>
  )
}
