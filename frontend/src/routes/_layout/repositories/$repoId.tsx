import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { ArrowLeft, GitBranch, Play } from "lucide-react"
import { toast } from "sonner"
import { AnalysesService, RepositoriesService } from "@/client"
import { GradeBadge } from "@/components/GradeBadge"
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

type RepoDetailSearch = { branch?: string }

export const Route = createFileRoute("/_layout/repositories/$repoId")({
  component: RepositoryDetail,
  validateSearch: (search: Record<string, unknown>): RepoDetailSearch => ({
    branch: typeof search.branch === "string" ? search.branch : undefined,
  }),
  head: () => ({
    meta: [{ title: "Repository - GreenSecOps" }],
  }),
})

function statusColor(status: string) {
  switch (status) {
    case "completed":
      return "bg-green-500/15 text-green-700 dark:text-green-400"
    case "running":
      return "bg-blue-500/15 text-blue-700 dark:text-blue-400"
    case "failed":
      return "bg-red-500/15 text-red-700 dark:text-red-400"
    case "pending":
      return "bg-yellow-500/15 text-yellow-700 dark:text-yellow-400"
    default:
      return "bg-muted text-muted-foreground"
  }
}

function RepositoryDetail() {
  const { repoId } = Route.useParams()
  const { branch } = Route.useSearch()
  const navigate = Route.useNavigate()
  const queryClient = useQueryClient()

  const { data: repo, isLoading: repoLoading } = useQuery({
    queryKey: ["repository", repoId],
    queryFn: () => RepositoriesService.getRepository({ repoId }),
  })

  const { data: analyses, isLoading: analysesLoading } = useQuery({
    queryKey: ["analyses", repoId, branch],
    queryFn: () =>
      AnalysesService.listAnalyses({
        repoId,
        branch: branch || undefined,
        limit: 100,
      }),
  })

  const triggerMutation = useMutation({
    mutationFn: () => AnalysesService.triggerAnalysis({ repoId }),
    onSuccess: () => {
      toast.success("Analysis queued")
      queryClient.invalidateQueries({ queryKey: ["analyses", repoId] })
    },
    onError: () => toast.error("Failed to trigger analysis"),
  })

  const branches = analyses
    ? [...new Set(analyses.map((a) => a.branch).filter(Boolean) as string[])]
    : []

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link
            to="/repositories"
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <div>
            {repoLoading ? (
              <Skeleton className="h-7 w-64" />
            ) : (
              <h1 className="text-2xl font-bold tracking-tight font-mono">
                {repo?.full_name}
              </h1>
            )}
            {repo && (
              <span className="inline-flex items-center gap-1 text-xs text-muted-foreground mt-0.5">
                <GitBranch className="h-3 w-3" />
                default: {repo.default_branch}
              </span>
            )}
          </div>
        </div>
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
              <div className="grid grid-cols-[1fr_auto_auto_auto_auto] items-center px-6 py-2 border-b text-xs font-medium text-muted-foreground uppercase tracking-wide gap-4">
                <span>Branch</span>
                <span>Triggered by</span>
                <span>Status</span>
                <span>Grade</span>
                <span>Date</span>
              </div>
              <div className="divide-y">
                {analyses.map((a) => (
                  <Link
                    key={a.id}
                    to="/analyses/$analysisId"
                    params={{ analysisId: a.id }}
                    className="grid grid-cols-[1fr_auto_auto_auto_auto] items-center px-6 py-3 gap-4 hover:bg-muted/40 transition-colors"
                  >
                    <span className="text-xs font-mono truncate">
                      {a.branch ?? "—"}
                    </span>
                    <span className="text-xs text-muted-foreground capitalize">
                      {a.triggered_by.replace("_", " ")}
                    </span>
                    <span
                      className={`text-xs font-medium px-2 py-0.5 rounded-full capitalize ${statusColor(a.status)}`}
                    >
                      {a.status}
                    </span>
                    <GradeBadge grade={a.grade ?? null} />
                    <span className="text-xs text-muted-foreground tabular-nums whitespace-nowrap">
                      {a.created_at
                        ? new Date(a.created_at).toLocaleDateString(undefined, {
                            month: "short",
                            day: "numeric",
                            hour: "2-digit",
                            minute: "2-digit",
                          })
                        : "—"}
                    </span>
                  </Link>
                ))}
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
