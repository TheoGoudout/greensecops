import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { GitBranch, Play, WifiOff } from "lucide-react"
import { toast } from "sonner"
import type { RepositoryPublic } from "@/client"
import { AnalysesService, RepositoriesService } from "@/client"
import { GradeBadge } from "@/components/GradeBadge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import useAuth from "@/hooks/useAuth"
import { useGitHubAppInstall } from "@/hooks/useGitHubAppInstall"

export const Route = createFileRoute("/_layout/repositories/")({
  component: Repositories,
  head: () => ({
    meta: [{ title: "Repositories - GreenSecOps" }],
  }),
})

function RepoRow({ repo }: { repo: RepositoryPublic }) {
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const isAccessible = repo.is_accessible ?? true
  // Auto-fix is a paid feature: only a superuser or a user on a paid tier may
  // enable it. The API enforces this too (HTTP 402); the disabled control is
  // just the UX affordance.
  const canAutoFix =
    (user?.is_superuser ?? false) || (user?.tier ?? "free") !== "free"

  const toggleMutation = useMutation({
    mutationFn: (enabled: boolean) =>
      RepositoriesService.toggleRepository({ repoId: repo.id, enabled }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["repositories"] })
    },
  })

  const autoFixMutation = useMutation({
    mutationFn: (enabled: boolean) =>
      RepositoriesService.toggleAutoFix({ repoId: repo.id, enabled }),
    onSuccess: (_data, enabled) => {
      toast.success(enabled ? "Auto-fix enabled" : "Auto-fix disabled")
      queryClient.invalidateQueries({ queryKey: ["repositories"] })
    },
    onError: () => toast.error("Failed to toggle auto-fix"),
  })

  const triggerMutation = useMutation({
    mutationFn: () => AnalysesService.triggerAnalysis({ repoId: repo.id }),
    onSuccess: () => {
      toast.success(`Analysis queued for ${repo.full_name}`)
      queryClient.invalidateQueries({ queryKey: ["analyses", repo.id] })
    },
    onError: () => {
      toast.error(`Failed to trigger analysis for ${repo.full_name}`)
    },
  })

  return (
    <div
      className={`grid grid-cols-[1fr_1fr_auto] sm:grid-cols-[2fr_1fr_1fr_1fr_1fr_auto] items-center px-6 py-4 gap-4 ${!isAccessible ? "opacity-50" : ""}`}
    >
      <div className="flex items-center gap-2 min-w-0">
        <Link
          to="/repositories/$repoId"
          params={{ repoId: repo.id }}
          className="text-sm font-medium truncate hover:underline"
        >
          {repo.full_name}
        </Link>
        {!isAccessible && (
          <Tooltip>
            <TooltipTrigger asChild>
              <WifiOff className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            </TooltipTrigger>
            <TooltipContent>
              GitHub App access lost. Reinstall the GitHub App to restore
              access.
            </TooltipContent>
          </Tooltip>
        )}
      </div>
      <span className="hidden sm:inline-flex items-center gap-1 text-xs font-mono bg-secondary text-secondary-foreground px-2 py-0.5 rounded-md w-fit">
        <GitBranch className="h-3 w-3" />
        {repo.default_branch}
      </span>
      <div className="hidden sm:block">
        <GradeBadge grade={repo.grade ?? null} />
      </div>
      <div className="flex items-center gap-2">
        <Switch
          checked={repo.enabled}
          onCheckedChange={(enabled) => toggleMutation.mutate(enabled)}
          disabled={toggleMutation.isPending || !isAccessible}
        />
        <span className="text-xs text-muted-foreground">
          {repo.enabled ? "Enabled" : "Disabled"}
        </span>
      </div>
      <div className="hidden sm:flex items-center gap-2">
        {canAutoFix ? (
          <Switch
            checked={repo.auto_fix_enabled ?? false}
            onCheckedChange={(enabled) => autoFixMutation.mutate(enabled)}
            disabled={autoFixMutation.isPending || !isAccessible}
          />
        ) : (
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="inline-flex">
                <Switch
                  checked={repo.auto_fix_enabled ?? false}
                  onCheckedChange={() => {}}
                  disabled
                  aria-label="Auto-fix (upgrade required)"
                />
              </span>
            </TooltipTrigger>
            <TooltipContent>
              Auto-fix is available on paid plans. Upgrade to enable it.
            </TooltipContent>
          </Tooltip>
        )}
        <span className="text-xs text-muted-foreground">Auto-fix</span>
      </div>
      <Button
        variant="ghost"
        size="icon"
        title="Trigger analysis"
        onClick={() => triggerMutation.mutate()}
        disabled={triggerMutation.isPending || !isAccessible}
      >
        <Play className="h-4 w-4" />
      </Button>
    </div>
  )
}

function Repositories() {
  const { openInstallPopup } = useGitHubAppInstall()
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
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Repositories</h1>
          <p className="text-muted-foreground">
            Manage which repositories GreenSecOps analyses
          </p>
        </div>
        <Button variant="outline" className="gap-2" onClick={openInstallPopup}>
          <GitBranch className="h-4 w-4" />
          Install GitHub App
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
              <div className="grid grid-cols-[1fr_1fr_auto] sm:grid-cols-[2fr_1fr_1fr_1fr_1fr_auto] items-center px-6 py-2 border-b text-xs font-medium text-muted-foreground uppercase tracking-wide">
                <span>Repository</span>
                <span className="hidden sm:block">Default branch</span>
                <span className="hidden sm:block">Latest grade</span>
                <span>Analysis</span>
                <span className="hidden sm:block">Auto-fix</span>
                <span className="w-8" />
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
