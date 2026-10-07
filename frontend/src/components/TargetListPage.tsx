import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { GitBranch, Loader2, type LucideIcon, Plus } from "lucide-react"
import { type ReactNode, useMemo, useState } from "react"
import { toast } from "sonner"
import { RepositoriesService } from "@/client"
import { targetsKey } from "@/components/FileTargetTab"
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

/**
 * An engine's org-wide page: every registered target, grouped by repository,
 * with a form to register another. Terraform, Ansible and Docker each wrote
 * this page out in full; what differs between them is in {@link TargetList}.
 */

interface ListedTarget {
  repo_id: string
  repo_full_name?: string | null
  latest_grade?: string | null
}

export interface TargetList<T extends ListedTarget> {
  keyPrefix: string
  title: string
  description: string
  /** "root", for "Add root" and "2 roots". */
  noun: string
  /** "Terraform roots", the column heading. */
  pluralLabel: string
  /** "Terraform root", for "Terraform root added". */
  targetLabel: string
  icon: LucideIcon
  placeholder: string
  /** Whether a blank path — the repository root — may be registered. */
  allowRepoRoot: boolean
  empty: ReactNode
  /** Where a repository's row leads: that engine's per-repository page. */
  repoLink:
    | "/infrastructure/$repoId"
    | "/infrastructure/$repoId/ansible"
    | "/docker/$repoId"
  listTargets: () => Promise<T[]>
  createTarget: (repoId: string, rootPath: string) => Promise<unknown>
}

interface RepoGroup {
  repoId: string
  repoName: string
  grades: (string | null | undefined)[]
}

export function TargetListPage<T extends ListedTarget>({
  list,
}: {
  list: TargetList<T>
}) {
  const queryClient = useQueryClient()
  const { openInstallPopup } = useGitHubAppInstall()
  const [selectedRepoId, setSelectedRepoId] = useState("")
  const [path, setPath] = useState("")

  // No repo_id is the org-wide mode of the endpoint, and every target already
  // carries its repo_full_name and latest_grade — no second query needed.
  const {
    data: targets,
    isLoading,
    isError,
  } = useQuery({
    queryKey: targetsKey(list.keyPrefix),
    queryFn: list.listTargets,
  })

  const { data: repos } = useQuery({
    queryKey: ["repositories", "picker"],
    queryFn: () => RepositoriesService.listRepositories({ limit: 200 }),
  })

  const createMutation = useMutation({
    mutationFn: (vars: { repoId: string; rootPath: string }) =>
      list.createTarget(vars.repoId, vars.rootPath),
    onSuccess: () => {
      toast.success(`${list.targetLabel} added`)
      setPath("")
      queryClient.invalidateQueries({ queryKey: targetsKey(list.keyPrefix) })
    },
    onError: (error) =>
      toast.error("Failed to add", { description: apiErrorDetail(error) }),
  })

  const groups = useMemo(() => {
    const byRepo = new Map<string, RepoGroup>()
    for (const target of targets ?? []) {
      const group = byRepo.get(target.repo_id) ?? {
        repoId: target.repo_id,
        repoName: target.repo_full_name ?? target.repo_id,
        grades: [],
      }
      group.grades.push(target.latest_grade)
      byRepo.set(target.repo_id, group)
    }
    return [...byRepo.values()].sort((a, b) =>
      a.repoName.localeCompare(b.repoName),
    )
  }, [targets])

  const canAdd =
    !!selectedRepoId &&
    (list.allowRepoRoot || !!path.trim()) &&
    !createMutation.isPending
  const add = () => {
    if (canAdd)
      createMutation.mutate({ repoId: selectedRepoId, rootPath: path.trim() })
  }
  const Icon = list.icon

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{list.title}</h1>
          <p className="text-muted-foreground">{list.description}</p>
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
            placeholder={list.placeholder}
            value={path}
            onChange={(e) => setPath(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") add()
            }}
            className="font-mono text-sm w-72"
          />
          <Button
            size="sm"
            variant="outline"
            className="gap-2"
            onClick={add}
            disabled={!canAdd}
          >
            {createMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Plus className="h-4 w-4" />
            )}
            Add {list.noun}
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
              Failed to load {list.pluralLabel.toLowerCase()}.
            </p>
          ) : !groups.length ? (
            <p className="text-sm text-muted-foreground p-6 text-center">
              {list.empty}
            </p>
          ) : (
            <>
              <div className="grid grid-cols-[2fr_1fr_1fr] items-center px-6 py-2 border-b text-xs font-medium text-muted-foreground font-mono uppercase tracking-wider">
                <span>Repository</span>
                <span>{list.pluralLabel}</span>
                <span>Worst grade</span>
              </div>
              <div className="divide-y">
                {groups.map((group) => (
                  <Link
                    key={group.repoId}
                    to={list.repoLink}
                    params={{ repoId: group.repoId }}
                    className="grid grid-cols-[2fr_1fr_1fr] items-center px-6 py-4 gap-4 hover:bg-muted/40 transition-colors"
                  >
                    <span className="flex items-center gap-2 min-w-0">
                      <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
                      <span className="text-sm font-medium font-mono truncate">
                        {group.repoName}
                      </span>
                    </span>
                    <span className="text-sm text-muted-foreground">
                      {group.grades.length} {list.noun}
                      {group.grades.length !== 1 ? "s" : ""}
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
