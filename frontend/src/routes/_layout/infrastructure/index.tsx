import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { Boxes, GitBranch, Loader2, Plus, ScrollText } from "lucide-react"
import { useMemo, useState } from "react"
import { toast } from "sonner"
import type { TerraformRootPublic } from "@/client"
import { AnsibleService, RepositoriesService, TerraformService } from "@/client"
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
  // Which engine the path being typed belongs to. Both register a folder
  // in a repo, so one form serves both rather than two near-identical ones.
  const [engine, setEngine] = useState<"terraform" | "ansible">("terraform")

  const {
    data: roots,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["terraform-roots"],
    queryFn: () => TerraformService.listTerraformRoots({}),
  })

  const { data: ansibleProjects } = useQuery({
    queryKey: ["ansible-projects"],
    queryFn: () => AnsibleService.listAnsibleProjects({}),
  })

  const { data: repos } = useQuery({
    queryKey: ["repositories", "for-terraform-picker"],
    queryFn: () => RepositoriesService.listRepositories({ limit: 200 }),
  })

  const createMutation = useMutation({
    mutationFn: (vars: {
      repoId: string
      rootPath: string
      engine: "terraform" | "ansible"
    }) =>
      vars.engine === "ansible"
        ? AnsibleService.createAnsibleProject({
            requestBody: { repo_id: vars.repoId, root_path: vars.rootPath },
          })
        : TerraformService.createTerraformRoot({
            requestBody: { repo_id: vars.repoId, root_path: vars.rootPath },
          }),
    onSuccess: (_data, vars) => {
      toast.success(
        vars.engine === "ansible"
          ? "Ansible project added"
          : "Terraform root added",
      )
      setNewRootPath("")
      queryClient.invalidateQueries({
        queryKey:
          vars.engine === "ansible"
            ? ["ansible-projects"]
            : ["terraform-roots"],
      })
    },
    onError: (error) =>
      toast.error("Failed to add", { description: apiErrorDetail(error) }),
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

  const ansibleGroups = useMemo(() => {
    const byRepo = new Map<
      string,
      {
        repoId: string
        repoName: string
        count: number
        grades: (string | null)[]
      }
    >()
    for (const project of ansibleProjects ?? []) {
      const existing = byRepo.get(project.repo_id)
      if (existing) {
        existing.count += 1
        existing.grades.push(project.latest_grade ?? null)
      } else {
        byRepo.set(project.repo_id, {
          repoId: project.repo_id,
          repoName: project.repo_full_name ?? project.repo_id,
          count: 1,
          grades: [project.latest_grade ?? null],
        })
      }
    }
    return [...byRepo.values()].sort((a, b) =>
      a.repoName.localeCompare(b.repoName),
    )
  }, [ansibleProjects])

  function handleAddRoot() {
    const path = newRootPath.trim()
    // An Ansible project may sit at the repository root, where the path is
    // legitimately empty; a Terraform root must name a folder.
    if (!selectedRepoId || (engine === "terraform" && !path)) return
    createMutation.mutate({ repoId: selectedRepoId, rootPath: path, engine })
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
          <Select
            value={engine}
            onValueChange={(v) => setEngine(v as "terraform" | "ansible")}
          >
            <SelectTrigger className="w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="terraform">Terraform</SelectItem>
              <SelectItem value="ansible">Ansible</SelectItem>
            </SelectContent>
          </Select>
          <Input
            placeholder={engine === "ansible" ? "ansible" : "infra/prod"}
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
              !selectedRepoId ||
              (engine === "terraform" && !newRootPath.trim()) ||
              createMutation.isPending
            }
          >
            {createMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Plus className="h-4 w-4" />
            )}
            Add {engine === "ansible" ? "project" : "root"}
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

      {ansibleGroups.length > 0 && (
        <Card>
          <CardContent className="p-0">
            <div className="grid grid-cols-[2fr_1fr_1fr] items-center px-6 py-2 border-b text-xs font-medium text-muted-foreground uppercase tracking-wide">
              <span>Repository</span>
              <span>Ansible projects</span>
              <span>Worst grade</span>
            </div>
            <div className="divide-y">
              {ansibleGroups.map((group) => (
                <Link
                  key={group.repoId}
                  to="/infrastructure/$repoId/ansible"
                  params={{ repoId: group.repoId }}
                  className="grid grid-cols-[2fr_1fr_1fr] items-center px-6 py-4 gap-4 hover:bg-muted/40 transition-colors"
                >
                  <span className="flex items-center gap-2 min-w-0">
                    <ScrollText className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <span className="text-sm font-medium font-mono truncate">
                      {group.repoName}
                    </span>
                  </span>
                  <span className="text-sm text-muted-foreground">
                    {group.count} project{group.count !== 1 ? "s" : ""}
                  </span>
                  <div>
                    <GradeBadge grade={worstGrade(group.grades)} />
                  </div>
                </Link>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
