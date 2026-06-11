import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { GitBranch, ToggleLeft, ToggleRight } from "lucide-react"
import type { RepositoryPublic } from "@/client"
import { AnalysesService, RepositoriesService } from "@/client"
import { GradeBadge } from "@/components/GradeBadge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

export const Route = createFileRoute("/_layout/repositories")({
  component: Repositories,
  head: () => ({
    meta: [{ title: "Repositories - GreenSecOps" }],
  }),
})

function RepoRow({ repo }: { repo: RepositoryPublic }) {
  const queryClient = useQueryClient()

  const { data: analyses } = useQuery({
    queryKey: ["analyses", repo.id, "latest"],
    queryFn: () =>
      AnalysesService.listAnalyses({
        repoId: repo.id,
        limit: 1,
        status: "completed",
      }),
  })

  const latest = analyses?.[0] ?? null

  const toggleMutation = useMutation({
    mutationFn: (enabled: boolean) =>
      RepositoriesService.toggleRepository({ repoId: repo.id, enabled }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["repositories"] })
    },
  })

  return (
    <div className="flex items-center justify-between py-4 gap-4">
      <div className="flex items-center gap-3 min-w-0">
        <GitBranch className="h-4 w-4 text-muted-foreground shrink-0" />
        <div className="min-w-0">
          <p className="text-sm font-medium truncate">{repo.full_name}</p>
          <p className="text-xs text-muted-foreground">
            {repo.default_branch} ·{" "}
            {repo.created_at
              ? new Date(repo.created_at).toLocaleDateString()
              : "—"}
          </p>
        </div>
      </div>

      <div className="flex items-center gap-3 shrink-0">
        {latest ? (
          <Link
            to="/analyses/$analysisId"
            params={{ analysisId: latest.id }}
            className="hover:opacity-80 transition-opacity"
          >
            <GradeBadge grade={latest.grade ?? null} />
          </Link>
        ) : (
          <GradeBadge grade={null} />
        )}

        <Button
          variant="ghost"
          size="sm"
          className="gap-1.5"
          onClick={() => toggleMutation.mutate(!repo.enabled)}
          disabled={toggleMutation.isPending}
          aria-label={repo.enabled ? "Disable repository" : "Enable repository"}
        >
          {repo.enabled ? (
            <ToggleRight className="h-5 w-5 text-primary" />
          ) : (
            <ToggleLeft className="h-5 w-5 text-muted-foreground" />
          )}
          <span className="text-xs">
            {repo.enabled ? "Enabled" : "Disabled"}
          </span>
        </Button>
      </div>
    </div>
  )
}

function Repositories() {
  const {
    data: repos,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["repositories"],
    queryFn: () => RepositoriesService.listRepositories({ limit: 200 }),
  })

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Repositories</h1>
        <p className="text-muted-foreground">
          Manage which repositories GreenSecOps analyses
        </p>
      </div>

      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="flex flex-col gap-2 p-6">
              {[...Array(5)].map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : isError ? (
            <p className="text-sm text-destructive p-6">
              Failed to load repositories.
            </p>
          ) : !repos?.length ? (
            <p className="text-sm text-muted-foreground p-6 text-center">
              No repositories found. Install the GitHub App to get started.
            </p>
          ) : (
            <div className="divide-y px-6">
              {repos.map((repo) => (
                <RepoRow key={repo.id} repo={repo} />
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
