import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { Boxes, GitBranch, Loader2, Plus } from "lucide-react"
import { useMemo, useState } from "react"
import { toast } from "sonner"
import type { TerraformRootPublic } from "@/client"
import { RepositoriesService, TerraformService } from "@/client"
import { GradeBadge } from "@/components/GradeBadge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { useGitHubAppInstall } from "@/hooks/useGitHubAppInstall"
import { apiErrorDetail } from "@/lib/api-error"
import { worstGrade } from "@/lib/grades"

export const Route = createFileRoute("/_layout/infrastructure/")({
  component: InfrastructurePage,
  head: () => ({
    meta: [{ title: "Infrastructure - GreenSecOps" }],
  }),
})

interface RepoGroup {
  repoId: string
  repoName: string
  roots: TerraformRootPublic[]
  worstGrade: string | null
}

function InfrastructurePage() {
  const queryClient = useQueryClient()
  const { openInstallPopup } = useGitHubAppInstall()
  const [selectedRepoId, setSelectedRepoId] = useState<string>("")
  const [newRootPath, setNewRootPath] = useState("")

  const {
    data: roots,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["terraform-roots"],
    queryFn: () => TerraformService.listTerraformRoots({}),
  })

  const { data: repos } = useQuery({
    queryKey: ["repositories", "for-terraform-picker"],
    queryFn: () => RepositoriesService.listRepositories({ limit: 200 }),
  })

  const createMutation = useMutation({
    mutationFn: (vars: { repoId: string; rootPath: string }) =>
      TerraformService.createTerraformRoot({
        requestBody: { repo_id: vars.repoId, root_path: vars.rootPath },
      }),
    onSuccess: () => {
      toast.success("Terraform root added")
      setNewRootPath("")
      queryClient.invalidateQueries({ queryKey: ["terraform-roots"] })
    },
    onError: (error) =>
      toast.error("Failed to add root", { description: apiErrorDetail(error) }),
  })

  const groups = useMemo<RepoGroup[]>(() => {
    const byRepo = new Map<string, RepoGroup>()
    for (const root of roots ?? []) {
      const existing = byRepo.get(root.repo_id)
      if (existing) {
        existing.roots.push(root)
      } else {
        byRepo.set(root.repo_id, {
          repoId: root.repo_id,
          repoName: root.repo_full_name ?? root.repo_id,
          roots: [root],
          worstGrade: null,
        })
      }
    }
    const list = [...byRepo.values()]
    for (const g of list)
      g.worstGrade = worstGrade(g.roots.map((r) => r.latest_grade))
    list.sort((a, b) => a.repoName.localeCompare(b.repoName))
    return list
  }, [roots])

  function handleAddRoot() {
    const path = newRootPath.trim()
    if (!path || !selectedRepoId) return
    createMutation.mutate({ repoId: selectedRepoId, rootPath: path })
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Terraform</h1>
          <p className="text-muted-foreground">
            Terraform roots, cloud posture and fixes, per repository.
          </p>
        </div>
        <Button variant="outline" className="gap-2" onClick={openInstallPopup}>
          <GitBranch className="h-4 w-4" />
          Install GitHub App
        </Button>
      </div>

      <Card>
        <CardContent className="flex items-center gap-2 py-4 flex-wrap">
          <Select value={selectedRepoId} onValueChange={setSelectedRepoId}>
            <SelectTrigger className="w-64">
              <SelectValue placeholder="Select a repository" />
            </SelectTrigger>
            <SelectContent>
              {(repos ?? []).map((repo) => (
                <SelectItem key={repo.id} value={repo.id}>
                  {repo.full_name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Input
            placeholder="infra/prod"
            value={newRootPath}
            onChange={(e) => setNewRootPath(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleAddRoot()
            }}
            className="font-mono text-sm max-w-xs"
          />
          <Button
            size="sm"
            variant="outline"
            className="gap-2"
            onClick={handleAddRoot}
            disabled={
              !selectedRepoId || !newRootPath.trim() || createMutation.isPending
            }
          >
            {createMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Plus className="h-4 w-4" />
            )}
            Add root
          </Button>
        </CardContent>
      </Card>

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
              Failed to load infrastructure.
            </p>
          ) : !groups.length ? (
            <p className="text-sm text-muted-foreground p-6 text-center">
              No Terraform roots configured. Pick a repository and add a folder
              path where your Terraform code lives (e.g.{" "}
              <code className="font-mono">infra</code> or{" "}
              <code className="font-mono">terraform/prod</code>) to start.
            </p>
          ) : (
            <>
              <div className="grid grid-cols-[2fr_1fr_1fr] items-center px-6 py-2 border-b text-xs font-medium text-muted-foreground uppercase tracking-wide">
                <span>Repository</span>
                <span>Terraform roots</span>
                <span>Worst grade</span>
              </div>
              <div className="divide-y">
                {groups.map((group) => (
                  <Link
                    key={group.repoId}
                    to="/infrastructure/$repoId"
                    params={{ repoId: group.repoId }}
                    className="grid grid-cols-[2fr_1fr_1fr] items-center px-6 py-4 gap-4 hover:bg-muted/40 transition-colors"
                  >
                    <span className="flex items-center gap-2 min-w-0">
                      <Boxes className="h-4 w-4 shrink-0 text-muted-foreground" />
                      <span className="text-sm font-medium font-mono truncate">
                        {group.repoName}
                      </span>
                    </span>
                    <span className="text-sm text-muted-foreground">
                      {group.roots.length} root
                      {group.roots.length !== 1 ? "s" : ""}
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
