import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  ChevronDown,
  ChevronRight,
  Loader2,
  Play,
  Plus,
  Trash2,
} from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import type { TerraformRootPublic } from "@/client"
import { RepositoriesService, TerraformService } from "@/client"
import { GradeBadge } from "@/components/GradeBadge"
import { StatusPill } from "@/components/StatusPill"
import { TerraformFindingRow } from "@/components/TerraformFindingRow"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { scanStatusColor, scanStatusLabel } from "@/lib/status-colors"
import { apiErrorDetail } from "@/utils"

export const Route = createFileRoute("/_layout/infrastructure/")({
  component: InfrastructurePage,
  head: () => ({
    meta: [{ title: "Infrastructure - GreenSecOps" }],
  }),
})

function InfrastructurePage() {
  const queryClient = useQueryClient()

  const [selectedRepoId, setSelectedRepoId] = useState<string>("")
  const [newRootPath, setNewRootPath] = useState("")
  const [openRoots, setOpenRoots] = useState<Set<string>>(new Set())
  const [historyOpenRoots, setHistoryOpenRoots] = useState<Set<string>>(
    new Set(),
  )

  const invalidateRoots = () =>
    queryClient.invalidateQueries({ queryKey: ["terraform-roots"] })

  const { data: repos } = useQuery({
    queryKey: ["repositories", "for-terraform-picker"],
    queryFn: () => RepositoriesService.listRepositories({ limit: 200 }),
  })

  const { data: roots, isLoading: rootsLoading } = useQuery({
    queryKey: ["terraform-roots"],
    queryFn: () => TerraformService.listTerraformRoots({}),
  })

  const createMutation = useMutation({
    mutationFn: (vars: { repoId: string; rootPath: string }) =>
      TerraformService.createTerraformRoot({
        requestBody: { repo_id: vars.repoId, root_path: vars.rootPath },
      }),
    onSuccess: () => {
      toast.success("Terraform root added")
      setNewRootPath("")
      invalidateRoots()
    },
    onError: (error) =>
      toast.error("Failed to add root", {
        description: apiErrorDetail(error),
      }),
  })

  const toggleMutation = useMutation({
    mutationFn: (vars: { rootId: string; enabled: boolean }) =>
      TerraformService.toggleTerraformRoot(vars),
    onSuccess: invalidateRoots,
    onError: (error) =>
      toast.error("Failed to update root", {
        description: apiErrorDetail(error),
      }),
  })

  const deleteMutation = useMutation({
    mutationFn: (rootId: string) =>
      TerraformService.deleteTerraformRoot({ rootId }),
    onSuccess: () => {
      toast.success("Terraform root removed")
      invalidateRoots()
    },
    onError: (error) =>
      toast.error("Failed to remove root", {
        description: apiErrorDetail(error),
      }),
  })

  const scanMutation = useMutation({
    mutationFn: (rootId: string) =>
      TerraformService.triggerTerraformScan({ rootId }),
    onSuccess: () => {
      toast.success("Scan queued")
      invalidateRoots()
    },
    onError: (error) =>
      toast.error("Failed to queue scan", {
        description: apiErrorDetail(error),
      }),
  })

  function toggleRootOpen(rootId: string) {
    setOpenRoots((prev) => {
      const next = new Set(prev)
      if (next.has(rootId)) next.delete(rootId)
      else next.add(rootId)
      return next
    })
  }

  function toggleHistoryOpen(rootId: string) {
    setHistoryOpenRoots((prev) => {
      const next = new Set(prev)
      if (next.has(rootId)) next.delete(rootId)
      else next.add(rootId)
      return next
    })
  }

  function handleAddRoot() {
    const path = newRootPath.trim()
    if (!path || !selectedRepoId) return
    createMutation.mutate({ repoId: selectedRepoId, rootPath: path })
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Infrastructure</h1>
        <p className="text-muted-foreground">
          Terraform static analysis across every repository you can access.
        </p>
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

      {rootsLoading ? (
        <div className="flex flex-col gap-4">
          {[...Array(2)].map((_, i) => (
            <Skeleton key={i} className="h-24 w-full" />
          ))}
        </div>
      ) : !roots?.length ? (
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground text-sm">
            No Terraform roots configured. Pick a repository and add a folder
            path where your Terraform code lives (e.g.{" "}
            <code className="font-mono">infra</code> or{" "}
            <code className="font-mono">terraform/prod</code>) to start scanning
            it.
          </CardContent>
        </Card>
      ) : (
        roots.map((root) => (
          <TerraformRootCard
            key={root.id}
            root={root}
            isOpen={openRoots.has(root.id)}
            onToggleOpen={() => toggleRootOpen(root.id)}
            historyOpen={historyOpenRoots.has(root.id)}
            onToggleHistory={() => toggleHistoryOpen(root.id)}
            onToggleEnabled={(enabled) =>
              toggleMutation.mutate({ rootId: root.id, enabled })
            }
            toggleMutationPending={
              toggleMutation.isPending &&
              toggleMutation.variables?.rootId === root.id
            }
            onScan={() => scanMutation.mutate(root.id)}
            scanMutationPending={
              scanMutation.isPending && scanMutation.variables === root.id
            }
            onDelete={() => {
              if (
                window.confirm(
                  `Remove Terraform root "${root.root_path}" from ${root.repo_full_name}? This deletes its scan history and findings.`,
                )
              ) {
                deleteMutation.mutate(root.id)
              }
            }}
            deleteMutationPending={
              deleteMutation.isPending && deleteMutation.variables === root.id
            }
          />
        ))
      )}
    </div>
  )
}

interface TerraformRootCardProps {
  root: TerraformRootPublic
  isOpen: boolean
  onToggleOpen: () => void
  historyOpen: boolean
  onToggleHistory: () => void
  onToggleEnabled: (enabled: boolean) => void
  toggleMutationPending: boolean
  onScan: () => void
  scanMutationPending: boolean
  onDelete: () => void
  deleteMutationPending: boolean
}

function TerraformRootCard({
  root,
  isOpen,
  onToggleOpen,
  historyOpen,
  onToggleHistory,
  onToggleEnabled,
  toggleMutationPending,
  onScan,
  scanMutationPending,
  onDelete,
  deleteMutationPending,
}: TerraformRootCardProps) {
  const { data: findings, isLoading: findingsLoading } = useQuery({
    queryKey: ["terraform-findings", root.id],
    queryFn: () => TerraformService.listTerraformFindings({ rootId: root.id }),
    enabled: isOpen,
  })

  const { data: scans } = useQuery({
    queryKey: ["terraform-scans", root.id],
    queryFn: () => TerraformService.listTerraformScans({ rootId: root.id }),
    enabled: isOpen && historyOpen,
  })

  return (
    <Card>
      <CardHeader className="pb-2 pt-4">
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 min-w-0">
          <CardTitle className="text-sm font-mono flex flex-wrap items-center gap-2 min-w-0 flex-1">
            <button
              type="button"
              onClick={onToggleOpen}
              className="shrink-0 text-muted-foreground hover:text-foreground transition-colors"
              aria-expanded={isOpen}
              title={isOpen ? "Collapse root" : "Expand root"}
            >
              {isOpen ? (
                <ChevronDown className="h-4 w-4" />
              ) : (
                <ChevronRight className="h-4 w-4" />
              )}
            </button>
            {root.repo_full_name && (
              <Link
                to="/repositories/$repoId"
                params={{ repoId: root.repo_id }}
                className="text-muted-foreground hover:text-foreground hover:underline shrink-0"
                onClick={(e) => e.stopPropagation()}
              >
                {root.repo_full_name}
              </Link>
            )}
            <span className="text-muted-foreground shrink-0">/</span>
            <span className="truncate min-w-0 flex-1">{root.root_path}</span>
            <GradeBadge
              grade={root.latest_grade ?? null}
              className="shrink-0"
            />
          </CardTitle>
          <div className="flex items-center gap-3 shrink-0">
            <div className="flex items-center gap-2">
              <Switch
                checked={root.enabled}
                onCheckedChange={onToggleEnabled}
                disabled={toggleMutationPending}
              />
              <span className="text-xs text-muted-foreground">
                {root.enabled ? "Enabled" : "Disabled"}
              </span>
            </div>
            <Button
              size="sm"
              variant="ghost"
              className="h-7 text-xs gap-1.5"
              onClick={onScan}
              disabled={!root.enabled || scanMutationPending}
              title={
                root.enabled
                  ? "Scan this root now"
                  : "Enable this root to scan it"
              }
            >
              {scanMutationPending ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Play className="h-3 w-3" />
              )}
              Scan now
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="h-7 text-xs gap-1.5 text-destructive hover:text-destructive"
              onClick={onDelete}
              disabled={deleteMutationPending}
            >
              {deleteMutationPending ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Trash2 className="h-3 w-3" />
              )}
              Remove
            </Button>
          </div>
        </div>
        {root.last_scanned_at && (
          <p className="text-xs text-muted-foreground">
            Last scanned{" "}
            {new Date(root.last_scanned_at).toLocaleDateString(undefined, {
              month: "short",
              day: "numeric",
              hour: "2-digit",
              minute: "2-digit",
            })}
          </p>
        )}
      </CardHeader>
      {isOpen && (
        <CardContent className="flex flex-col gap-3">
          <div className="rounded-md border">
            <div className="px-4 py-2 text-xs font-medium text-muted-foreground border-b">
              Open findings
            </div>
            {findingsLoading ? (
              <div className="p-4">
                <Skeleton className="h-16 w-full" />
              </div>
            ) : !findings?.length ? (
              <p className="text-sm text-muted-foreground p-6 text-center">
                No open findings.
                {!root.last_scanned_at && " Run a scan to check this root."}
              </p>
            ) : (
              <div className="divide-y">
                {findings.map((finding) => (
                  <TerraformFindingRow key={finding.id} finding={finding} />
                ))}
              </div>
            )}
          </div>

          <div className="rounded-md border">
            <button
              type="button"
              onClick={onToggleHistory}
              className="flex w-full items-center gap-2 px-4 py-2 text-left text-xs font-medium text-muted-foreground hover:bg-muted/40 transition-colors"
            >
              {historyOpen ? (
                <ChevronDown className="h-3.5 w-3.5" />
              ) : (
                <ChevronRight className="h-3.5 w-3.5" />
              )}
              Scan history
            </button>
            {historyOpen && (
              <div className="divide-y border-t">
                {!scans?.length ? (
                  <p className="text-sm text-muted-foreground p-6 text-center">
                    No scans yet.
                  </p>
                ) : (
                  scans.map((scan) => (
                    <div
                      key={scan.id}
                      className="flex items-center justify-between gap-4 px-4 py-2.5 text-xs"
                    >
                      <StatusPill colorClass={scanStatusColor(scan.status)}>
                        {scanStatusLabel(scan.status)}
                      </StatusPill>
                      <span className="text-muted-foreground capitalize">
                        {scan.triggered_by.replace(/_/g, " ")}
                      </span>
                      <GradeBadge grade={scan.grade ?? null} />
                      <span className="text-muted-foreground tabular-nums">
                        {scan.created_at
                          ? new Date(scan.created_at).toLocaleDateString(
                              undefined,
                              {
                                month: "short",
                                day: "numeric",
                                hour: "2-digit",
                                minute: "2-digit",
                              },
                            )
                          : "—"}
                      </span>
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
        </CardContent>
      )}
    </Card>
  )
}
