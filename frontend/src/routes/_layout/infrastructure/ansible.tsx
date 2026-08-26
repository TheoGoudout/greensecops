import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { GitBranch, Loader2, Plus, ScrollText } from "lucide-react"
import { useMemo, useState } from "react"
import { toast } from "sonner"
import { AnsibleService, RepositoriesService } from "@/client"
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

// A static sibling of `$repoId`, the same way `badges` is: the router prefers
// the literal segment, and `AppSidebar` excludes both names when it reads a
// repo id out of the path.
export const Route = createFileRoute("/_layout/infrastructure/ansible")({
  component: AnsibleIndexPage,
  head: () => ({
    meta: [{ title: "Ansible - GreenSecOps" }],
  }),
})

interface RepoGroup {
  repoId: string
  repoName: string
  count: number
  grades: (string | null)[]
}

function AnsibleIndexPage() {
  const queryClient = useQueryClient()
  const { openInstallPopup } = useGitHubAppInstall()
  const [selectedRepoId, setSelectedRepoId] = useState<string>("")
  const [newRootPath, setNewRootPath] = useState("")

  const {
    data: projects,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["ansible-projects"],
    queryFn: () => AnsibleService.listAnsibleProjects({}),
  })

  const { data: repos } = useQuery({
    queryKey: ["repositories", "for-ansible-picker"],
    queryFn: () => RepositoriesService.listRepositories({ limit: 200 }),
  })

  const createMutation = useMutation({
    mutationFn: (vars: { repoId: string; rootPath: string }) =>
      AnsibleService.createAnsibleProject({
        requestBody: { repo_id: vars.repoId, root_path: vars.rootPath },
      }),
    onSuccess: () => {
      toast.success("Ansible project added")
      setNewRootPath("")
      queryClient.invalidateQueries({ queryKey: ["ansible-projects"] })
    },
    onError: (error) =>
      toast.error("Failed to add", { description: apiErrorDetail(error) }),
  })

  const groups = useMemo<RepoGroup[]>(() => {
    const byRepo = new Map<string, RepoGroup>()
    for (const project of projects ?? []) {
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
  }, [projects])

  function handleAdd() {
    // Unlike a Terraform root, an Ansible project may sit at the repository
    // root, where the path is legitimately empty — so only the repo is
    // required here.
    if (!selectedRepoId) return
    createMutation.mutate({
      repoId: selectedRepoId,
      rootPath: newRootPath.trim(),
    })
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Ansible</h1>
          <p className="text-muted-foreground">
            Playbooks, roles and fixes, per repository.
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
            placeholder="deploy/ansible (blank = repository root)"
            value={newRootPath}
            onChange={(e) => setNewRootPath(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleAdd()
            }}
            className="font-mono text-sm w-72"
          />
          <Button
            size="sm"
            variant="outline"
            className="gap-2"
            onClick={handleAdd}
            disabled={!selectedRepoId || createMutation.isPending}
          >
            {createMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Plus className="h-4 w-4" />
            )}
            Add project
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
              Failed to load Ansible projects.
            </p>
          ) : !groups.length ? (
            <p className="text-sm text-muted-foreground p-6 text-center">
              No Ansible projects configured. Pick a repository and add the
              folder holding your playbooks and roles (e.g.{" "}
              <code className="font-mono">deploy/ansible</code>), or leave the
              path blank if they live at the repository root.
            </p>
          ) : (
            <>
              <div className="grid grid-cols-[2fr_1fr_1fr] items-center px-6 py-2 border-b text-xs font-medium text-muted-foreground uppercase tracking-wide">
                <span>Repository</span>
                <span>Ansible projects</span>
                <span>Worst grade</span>
              </div>
              <div className="divide-y">
                {groups.map((group) => (
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
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
