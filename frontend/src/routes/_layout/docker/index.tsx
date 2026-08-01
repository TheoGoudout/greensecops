import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { Container, GitBranch } from "lucide-react"
import { useMemo } from "react"
import type { DockerTargetPublic } from "@/client"
import { DockerService } from "@/client"
import { GradeBadge } from "@/components/GradeBadge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useGitHubAppInstall } from "@/hooks/useGitHubAppInstall"
import { worstGrade } from "@/lib/grades"

export const Route = createFileRoute("/_layout/docker/")({
  component: DockerPage,
  head: () => ({
    meta: [{ title: "Docker - GreenSecOps" }],
  }),
})

interface RepoGroup {
  repoId: string
  repoName: string
  targets: DockerTargetPublic[]
  worstGrade: string | null
}

function DockerPage() {
  const { openInstallPopup } = useGitHubAppInstall()

  // No repo_id is the org-wide mode of the endpoint, and DockerTargetPublic
  // already carries repo_full_name and latest_grade — no second query needed.
  const {
    data: targets,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["docker-targets"],
    queryFn: () => DockerService.listDockerTargets({}),
  })

  const groups = useMemo<RepoGroup[]>(() => {
    const byRepo = new Map<string, RepoGroup>()
    for (const target of targets ?? []) {
      const existing = byRepo.get(target.repo_id)
      if (existing) {
        existing.targets.push(target)
      } else {
        byRepo.set(target.repo_id, {
          repoId: target.repo_id,
          repoName: target.repo_full_name ?? target.repo_id,
          targets: [target],
          worstGrade: null,
        })
      }
    }
    const list = [...byRepo.values()]
    for (const g of list)
      g.worstGrade = worstGrade(g.targets.map((t) => t.latest_grade))
    list.sort((a, b) => a.repoName.localeCompare(b.repoName))
    return list
  }, [targets])

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Docker</h1>
          <p className="text-muted-foreground">
            Dockerfile and Compose static analysis, fixes and PRs, per
            repository.
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
              {[...Array(4)].map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : isError ? (
            <p className="text-sm text-destructive p-6">
              Failed to load Docker targets.
            </p>
          ) : !groups.length ? (
            <p className="text-sm text-muted-foreground p-6 text-center">
              No Docker targets yet. One is created automatically for every
              repository the GitHub App syncs.
            </p>
          ) : (
            <>
              <div className="grid grid-cols-[2fr_1fr_1fr] items-center px-6 py-2 border-b text-xs font-medium text-muted-foreground uppercase tracking-wide">
                <span>Repository</span>
                <span>Docker targets</span>
                <span>Worst grade</span>
              </div>
              <div className="divide-y">
                {groups.map((group) => (
                  <Link
                    key={group.repoId}
                    to="/docker/$repoId"
                    params={{ repoId: group.repoId }}
                    className="grid grid-cols-[2fr_1fr_1fr] items-center px-6 py-4 gap-4 hover:bg-muted/40 transition-colors"
                  >
                    <span className="flex items-center gap-2 min-w-0">
                      <Container className="h-4 w-4 shrink-0 text-muted-foreground" />
                      <span className="text-sm font-medium font-mono truncate">
                        {group.repoName}
                      </span>
                    </span>
                    <span className="text-sm text-muted-foreground">
                      {group.targets.length} target
                      {group.targets.length !== 1 ? "s" : ""}
                    </span>
                    <div>
                      <GradeBadge grade={group.worstGrade} />
                    </div>
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
