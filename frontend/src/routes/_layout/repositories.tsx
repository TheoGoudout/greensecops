import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { GitBranch } from "lucide-react"
import type { RepositoryPublic } from "@/client"
import { AnalysesService, RepositoriesService } from "@/client"
import { GradeBadge } from "@/components/GradeBadge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"

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
    <div className="grid grid-cols-[2fr_1fr_1fr_1fr] items-center px-6 py-4 gap-4">
      <Link
        to="/repositories/$repoId"
        params={{ repoId: repo.id }}
        className="text-sm font-medium truncate hover:underline"
      >
        {repo.full_name}
      </Link>
      <span className="inline-flex items-center gap-1 text-xs font-mono bg-secondary text-secondary-foreground px-2 py-0.5 rounded-md w-fit">
        <GitBranch className="h-3 w-3" />
        {repo.default_branch}
      </span>
      <div>
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
      </div>
      <div className="flex items-center gap-2">
        <Switch
          checked={repo.enabled}
          onCheckedChange={(enabled) => toggleMutation.mutate(enabled)}
          disabled={toggleMutation.isPending}
        />
        <span className="text-xs text-muted-foreground">
          {repo.enabled ? "Enabled" : "Disabled"}
        </span>
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
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Repositories</h1>
          <p className="text-muted-foreground">
            Manage which repositories GreenSecOps analyses
          </p>
        </div>
        <Button variant="outline" className="gap-2" asChild>
          <a
            href={`https://github.com/apps/${import.meta.env.VITE_GITHUB_APP_NAME}/installations/new`}
            target="_blank"
            rel="noopener noreferrer"
          >
            <GitBranch className="h-4 w-4" />
            Install GitHub App
          </a>
        </Button>
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
            <>
              <div className="grid grid-cols-[2fr_1fr_1fr_1fr] items-center px-6 py-2 border-b text-xs font-medium text-muted-foreground uppercase tracking-wide">
                <span>Repository</span>
                <span>Default branch</span>
                <span>Latest grade</span>
                <span>Analysis</span>
              </div>
              <div className="divide-y">
                {repos.map((repo) => (
                  <RepoRow key={repo.id} repo={repo} />
                ))}
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
