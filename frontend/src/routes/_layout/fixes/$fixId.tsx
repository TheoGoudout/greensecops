import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { html as diff2htmlString } from "diff2html"
import { ColorSchemeType } from "diff2html/lib/types"
import "diff2html/bundles/css/diff2html.min.css"
import { AlertCircle, ArrowLeft, GitPullRequest } from "lucide-react"
import { toast } from "sonner"
import { FixesService, IssuesService } from "@/client"
import { CategoryIcon } from "@/components/CategoryIcon"
import { SeverityChip } from "@/components/SeverityChip"
import { useTheme } from "@/components/theme-provider"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

type FixDetailSearch = { repoId?: string }

export const Route = createFileRoute("/_layout/fixes/$fixId")({
  component: FixDetail,
  validateSearch: (search: Record<string, unknown>): FixDetailSearch => ({
    repoId: typeof search.repoId === "string" ? search.repoId : undefined,
  }),
  head: () => ({
    meta: [{ title: "Fix - GreenSecOps" }],
  }),
})

function fixStatusColor(status: string): string {
  switch (status) {
    case "delivered":
      return "bg-green-500/15 text-green-700 dark:text-green-400"
    case "ready":
      return "bg-blue-500/15 text-blue-700 dark:text-blue-400"
    case "failed":
      return "bg-red-500/15 text-red-700 dark:text-red-400"
    case "rejected":
      return "bg-muted text-muted-foreground line-through"
    default:
      return "bg-yellow-500/15 text-yellow-700 dark:text-yellow-400"
  }
}

function FixDetail() {
  const { fixId } = Route.useParams()
  const { repoId } = Route.useSearch()
  const queryClient = useQueryClient()
  const { resolvedTheme } = useTheme()

  const {
    data: fix,
    isLoading: fixLoading,
    isError: fixError,
  } = useQuery({
    queryKey: ["fix", fixId],
    queryFn: () => FixesService.getFix({ fixId }),
  })

  const { data: issue, isLoading: issueLoading } = useQuery({
    queryKey: ["issue", fix?.issue_id],
    queryFn: () => IssuesService.getIssue({ issueId: fix!.issue_id }),
    enabled: !!fix?.issue_id,
  })

  const deliverMutation = useMutation({
    mutationFn: () => FixesService.triggerFixDelivery({ fixId }),
    onSuccess: () => {
      toast.success("PR creation queued")
      queryClient.invalidateQueries({ queryKey: ["fix", fixId] })
    },
    onError: () => toast.error("Failed to queue PR delivery"),
  })

  const rejectMutation = useMutation({
    mutationFn: () => FixesService.rejectFix({ fixId }),
    onSuccess: () => {
      toast.success("Fix rejected")
      queryClient.invalidateQueries({ queryKey: ["fix", fixId] })
    },
    onError: () => toast.error("Failed to reject fix"),
  })

  const diffHtml = fix?.diff_patch
    ? diff2htmlString(fix.diff_patch, {
        drawFileList: false,
        matching: "lines",
        outputFormat: "line-by-line",
        colorScheme:
          resolvedTheme === "dark"
            ? ColorSchemeType.DARK
            : ColorSchemeType.LIGHT,
      })
    : null

  if (fixError) {
    return (
      <Alert variant="destructive">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>Fix not found or failed to load.</AlertDescription>
      </Alert>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link
            to={repoId ? "/repositories/$repoId" : "/repositories"}
            params={repoId ? { repoId } : undefined}
            search={repoId ? { tab: "fixes" } : undefined}
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Fix Detail</h1>
            <p className="text-muted-foreground text-sm font-mono">{fixId}</p>
          </div>
        </div>
        {fix && (
          <div className="flex items-center gap-2">
            {fix.status === "ready" && (
              <>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => rejectMutation.mutate()}
                  disabled={rejectMutation.isPending}
                >
                  {rejectMutation.isPending ? "Rejecting…" : "Reject"}
                </Button>
                <Button
                  size="sm"
                  className="gap-2"
                  onClick={() => deliverMutation.mutate()}
                  disabled={
                    deliverMutation.isPending || deliverMutation.isSuccess
                  }
                >
                  <GitPullRequest className="h-4 w-4" />
                  {deliverMutation.isPending
                    ? "Queuing…"
                    : deliverMutation.isSuccess
                      ? "Queued"
                      : "Create PR"}
                </Button>
              </>
            )}
            {fix.pr_url && (
              <a
                href={fix.pr_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1.5 text-sm text-blue-600 dark:text-blue-400 hover:underline"
              >
                <GitPullRequest className="h-4 w-4" />
                View PR
              </a>
            )}
          </div>
        )}
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium text-muted-foreground uppercase tracking-wide">
            Issue
          </CardTitle>
        </CardHeader>
        <CardContent>
          {fixLoading || issueLoading ? (
            <div className="flex flex-col gap-2">
              <Skeleton className="h-5 w-full" />
              <Skeleton className="h-4 w-48" />
            </div>
          ) : issue ? (
            <div className="flex items-start gap-3">
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
                  {fix && (
                    <span
                      className={`text-xs font-medium px-2 py-0.5 rounded-full capitalize ${fixStatusColor(fix.status)}`}
                    >
                      {fix.status}
                    </span>
                  )}
                  <span className="text-sm">{issue.message}</span>
                </div>
                {issue.line_start != null && (
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Line {issue.line_start}
                    {issue.line_end && issue.line_end !== issue.line_start
                      ? `–${issue.line_end}`
                      : ""}
                  </p>
                )}
                {issue.workflow_file_path && (
                  <p className="text-xs text-muted-foreground font-mono mt-0.5">
                    {issue.workflow_file_path}
                  </p>
                )}
              </div>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              Issue details unavailable.
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium text-muted-foreground uppercase tracking-wide">
            Diff
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0 overflow-hidden rounded-b-lg">
          {fixLoading ? (
            <div className="flex flex-col gap-2 p-6">
              {[...Array(6)].map((_, i) => (
                <Skeleton key={i} className="h-5 w-full" />
              ))}
            </div>
          ) : diffHtml ? (
            <div
              className="diff2html-wrapper text-xs overflow-x-auto"
              // biome-ignore lint/security/noDangerouslySetInnerHtml: diff2html renders structured patch data from the API, not raw user input
              dangerouslySetInnerHTML={{ __html: diffHtml }}
            />
          ) : (
            <p className="text-sm text-muted-foreground p-6 text-center">
              No diff available yet.{" "}
              {fix?.status === "pending" || fix?.status === "generating"
                ? "Fix is still being generated."
                : ""}
            </p>
          )}
        </CardContent>
      </Card>

      {fix && (
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <span>Model: {fix.llm_model}</span>
          {fix.created_at && (
            <span>
              Created:{" "}
              {new Date(fix.created_at).toLocaleDateString(undefined, {
                month: "short",
                day: "numeric",
                hour: "2-digit",
                minute: "2-digit",
              })}
            </span>
          )}
        </div>
      )}
    </div>
  )
}
