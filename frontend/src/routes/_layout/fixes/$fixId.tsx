import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { AlertCircle, ArrowLeft, GitPullRequest, RefreshCw } from "lucide-react"
import { toast } from "sonner"
import { WorkflowService } from "@/client"
import { CategoryIcon } from "@/components/CategoryIcon"
import { FileViewer } from "@/components/FileViewer"
import { RuleSlugChip } from "@/components/RuleSlugChip"
import { SeverityChip } from "@/components/SeverityChip"
import { StatusPill } from "@/components/StatusPill"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { apiErrorDetail } from "@/lib/api-error"
import { formatDateTime } from "@/lib/format"
import { fixStatusColor } from "@/lib/status-colors"

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

function FixDetail() {
  const { fixId } = Route.useParams()
  const { repoId } = Route.useSearch()
  const queryClient = useQueryClient()

  const {
    data: fix,
    isLoading: fixLoading,
    isError: fixError,
  } = useQuery({
    queryKey: ["fix", fixId],
    queryFn: () => WorkflowService.getFix({ fixId }),
  })

  const deliverMutation = useMutation({
    mutationFn: () => WorkflowService.deliverFix({ fixId }),
    onSuccess: () => {
      toast.success("PR creation queued")
      queryClient.invalidateQueries({ queryKey: ["fix", fixId] })
    },
    onError: (error) =>
      toast.error("Failed to queue PR delivery", {
        description: apiErrorDetail(error),
      }),
  })

  const rejectMutation = useMutation({
    mutationFn: () => WorkflowService.rejectFix({ fixId }),
    onSuccess: () => {
      toast.success("Fix rejected")
      queryClient.invalidateQueries({ queryKey: ["fix", fixId] })
    },
    onError: () => toast.error("Failed to reject fix"),
  })

  const retryMutation = useMutation({
    mutationFn: () => WorkflowService.retryFix({ fixId }),
    onSuccess: () => {
      toast.success("Retrying fix")
      queryClient.invalidateQueries({ queryKey: ["fix", fixId] })
      if (repoId) {
        queryClient.invalidateQueries({ queryKey: ["fixes", "repo", repoId] })
      }
    },
    onError: (error) =>
      toast.error("Failed to retry fix", {
        description: apiErrorDetail(error),
      }),
  })

  if (fixError) {
    return (
      <Alert variant="destructive">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>Fix not found or failed to load.</AlertDescription>
      </Alert>
    )
  }

  const findings = fix?.findings ?? []

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link
            to={repoId ? "/workflows/$repoId/static-analysis" : "/workflows"}
            params={repoId ? { repoId } : undefined}
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Fix Detail</h1>
            <p className="text-muted-foreground text-sm font-mono">
              {fix?.file_path ?? fixId}
            </p>
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
            {fix.status === "failed" && (
              <Button
                variant="outline"
                size="sm"
                className="gap-2"
                onClick={() => retryMutation.mutate()}
                disabled={retryMutation.isPending || retryMutation.isSuccess}
              >
                <RefreshCw className="h-4 w-4" />
                {retryMutation.isPending
                  ? "Retrying…"
                  : retryMutation.isSuccess
                    ? "Queued"
                    : "Retry"}
              </Button>
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
          <div className="flex items-center gap-2">
            <CardTitle className="text-sm font-medium text-muted-foreground uppercase tracking-wide">
              Issues addressed
            </CardTitle>
            {fix && (
              <StatusPill
                colorClass={fixStatusColor(fix.status)}
                className="capitalize"
              >
                {fix.status}
              </StatusPill>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {fixLoading ? (
            <div className="flex flex-col gap-2">
              <Skeleton className="h-5 w-full" />
              <Skeleton className="h-4 w-48" />
            </div>
          ) : findings.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Finding details unavailable.
            </p>
          ) : (
            <div className="flex flex-col gap-3">
              {findings.map((finding) => (
                <div key={finding.id} className="flex items-start gap-3">
                  {finding.category && (
                    <CategoryIcon
                      category={finding.category}
                      className="mt-0.5 shrink-0 text-base"
                    />
                  )}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      {finding.severity && (
                        <SeverityChip severity={finding.severity} />
                      )}
                      {finding.rule_slug && (
                        <RuleSlugChip>{finding.rule_slug}</RuleSlugChip>
                      )}
                      <span className="text-sm">{finding.message}</span>
                    </div>
                    {finding.line_start != null && (
                      <p className="text-xs text-muted-foreground mt-0.5">
                        Line {finding.line_start}
                        {finding.line_end &&
                        finding.line_end !== finding.line_start
                          ? `–${finding.line_end}`
                          : ""}
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {fix?.error_message && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{fix.error_message}</AlertDescription>
        </Alert>
      )}

      {fix?.base_content && (
        <FileViewer
          path={fix.file_path ?? ""}
          rawContent={fix.base_content}
          grammar="yaml"
          fullContent={fix.full_content ?? undefined}
          annotations={[]}
          noun="issue"
          fileLevelLabel="Workflow-level issues"
        />
      )}

      {fix && (
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <span>Model: {fix.llm_model}</span>
          {fix.created_at && (
            <span>Created: {formatDateTime(fix.created_at)}</span>
          )}
        </div>
      )}
    </div>
  )
}
