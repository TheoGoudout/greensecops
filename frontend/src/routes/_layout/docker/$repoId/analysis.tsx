import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import {
  ChevronDown,
  ChevronRight,
  GitPullRequest,
  Play,
  Trash2,
  Wand2,
} from "lucide-react"
import { useMemo, useState } from "react"
import type {
  DockerFilePublic,
  DockerFindingPublic,
  DockerFixPublic,
  DockerTargetPublic,
  PullRequestPublic,
} from "@/client"
import { DockerService, WorkflowService } from "@/client"
import { DockerFindingRow } from "@/components/DockerFindingRow"
import { FileViewer } from "@/components/FileViewer"
import { GradeBadge } from "@/components/GradeBadge"
import { StatusPill } from "@/components/StatusPill"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { useEngineTarget } from "@/hooks/useEngineTarget"
import { dockerFixBranch } from "@/lib/delivery"
import { severityRank } from "@/lib/severity"
import { fixStatusColor } from "@/lib/status-colors"

export const Route = createFileRoute("/_layout/docker/$repoId/analysis")({
  component: DockerAnalysisTab,
  head: () => ({
    meta: [{ title: "Docker analysis - GreenSecOps" }],
  }),
})

// Fix statuses a worker is actively processing — used to disable actions.
// Mirrors the server-side _IN_FLIGHT_FIX_STATUSES.
const IN_FLIGHT = new Set(["pending", "generating", "delivering"])

function DockerAnalysisTab() {
  const { repoId } = Route.useParams()
  const [openTargets, setOpenTargets] = useState<Set<string>>(new Set())

  const { data: targets, isLoading } = useQuery({
    queryKey: ["docker-targets", "repo", repoId],
    queryFn: () => DockerService.listTargets({ repoId }),
  })

  // A ready fix carries no PR of its own, so whether one already exists for
  // its deterministic branch has to come from the real PullRequest rows.
  const { data: pullRequests } = useQuery({
    queryKey: ["pull-requests", "repo", repoId],
    queryFn: () => WorkflowService.listPullRequests({ repoId }),
  })

  const prByBranch = useMemo(() => {
    const map = new Map<string, PullRequestPublic>()
    for (const pr of pullRequests ?? []) {
      if (pr.pr_branch) map.set(pr.pr_branch, pr)
    }
    return map
  }, [pullRequests])

  const toggleOpen = (id: string) =>
    setOpenTargets((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })

  if (isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-28 w-full" />
      </div>
    )
  }

  if (!targets || targets.length === 0) {
    return (
      <Card>
        <CardContent className="py-10 text-center text-sm text-muted-foreground">
          No Docker targets yet. One is created automatically when the GitHub
          App syncs this repository.
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      {targets.map((target) => (
        <TargetCard
          key={target.id}
          target={target}
          isOpen={openTargets.has(target.id)}
          onToggleOpen={() => toggleOpen(target.id)}
          existingPr={prByBranch.get(dockerFixBranch(target.id))}
        />
      ))}
    </div>
  )
}

function TargetCard({
  target,
  isOpen,
  onToggleOpen,
  existingPr,
}: {
  target: DockerTargetPublic
  isOpen: boolean
  onToggleOpen: () => void
  existingPr?: PullRequestPublic
}) {
  const {
    files,
    findings,
    fixes,
    toggleMutation,
    scanMutation,
    deleteMutation,
    generateMutation,
    deliverMutation,
  } = useEngineTarget<DockerFilePublic, DockerFindingPublic, DockerFixPublic>(
    target.id,
    isOpen,
    {
      keyPrefix: "docker",
      targetLabel: "Target",
      listFiles: () => DockerService.listFiles({ targetId: target.id }),
      listFindings: () => DockerService.listFindings({ targetId: target.id }),
      listFixes: () => DockerService.listFixes({ targetId: target.id }),
      toggle: (enabled) =>
        DockerService.updateTarget({
          targetId: target.id,
          requestBody: { enabled },
        }),
      scan: () => DockerService.triggerScan({ targetId: target.id }),
      remove: () => DockerService.deleteTarget({ targetId: target.id }),
      generate: (findingIds) =>
        DockerService.generateFixes({
          targetId: target.id,
          requestBody: findingIds.length
            ? { finding_ids: findingIds }
            : { finding_ids: null },
        }),
      deliver: (force) =>
        DockerService.deliverFixes({ targetId: target.id, force }),
    },
  )

  const fixByFile = useMemo(() => {
    const map = new Map<string, DockerFixPublic>()
    for (const fix of fixes ?? []) map.set(fix.file_path, fix)
    return map
  }, [fixes])

  const hasReadyFix = (fixes ?? []).some((f) => f.status === "ready")
  const deliverLabel =
    existingPr?.pr_state === "closed"
      ? "Reopen PR"
      : existingPr
        ? "Update PR"
        : "Create PR"

  const findingsByFile = useMemo(() => {
    const map = new Map<string, DockerFindingPublic[]>()
    for (const finding of findings ?? []) {
      const list = map.get(finding.file_path) ?? []
      list.push(finding)
      map.set(finding.file_path, list)
    }
    for (const list of map.values()) {
      list.sort((a, b) => severityRank(a.severity) - severityRank(b.severity))
    }
    return map
  }, [findings])

  const openFindingCount = findings?.length ?? 0

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
        <div className="flex items-start gap-2 min-w-0">
          <button
            type="button"
            onClick={onToggleOpen}
            aria-expanded={isOpen}
            aria-label={isOpen ? "Collapse target" : "Expand target"}
            className="mt-0.5 text-muted-foreground hover:text-foreground transition-colors"
          >
            {isOpen ? (
              <ChevronDown className="size-4" />
            ) : (
              <ChevronRight className="size-4" />
            )}
          </button>
          <div className="min-w-0">
            <CardTitle className="font-mono text-sm break-all">
              {target.root_path === ""
                ? "/ (repository root)"
                : target.root_path}
            </CardTitle>
            <p className="text-xs text-muted-foreground mt-1">
              {target.last_scanned_at
                ? `Last scanned ${new Date(target.last_scanned_at).toLocaleString()}`
                : "Never scanned"}
              {openFindingCount > 0 &&
                ` · ${openFindingCount} open finding${openFindingCount !== 1 ? "s" : ""}`}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <GradeBadge grade={target.latest_grade ?? null} />
          <Switch
            checked={target.enabled}
            onCheckedChange={() => toggleMutation.mutate(!target.enabled)}
            aria-label="Enable target"
          />
          <Button
            size="sm"
            variant="outline"
            disabled={!target.enabled || scanMutation.isPending}
            onClick={() => scanMutation.mutate()}
          >
            <Play className="size-3.5" />
            Scan now
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="text-destructive hover:text-destructive"
            onClick={() => {
              if (
                window.confirm(
                  `Remove the Docker target "${target.root_path || "/"}"?`,
                )
              ) {
                deleteMutation.mutate()
              }
            }}
          >
            <Trash2 className="size-3.5" />
          </Button>
        </div>
      </CardHeader>

      {isOpen && (
        <CardContent className="flex flex-col gap-4">
          {(openFindingCount > 0 || hasReadyFix) && (
            <div className="flex flex-wrap gap-2">
              {openFindingCount > 0 && (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={generateMutation.isPending}
                  onClick={() => generateMutation.mutate([])}
                >
                  <Wand2 className="size-3.5" />
                  Generate all fixes
                </Button>
              )}
              {hasReadyFix && (
                <Button
                  size="sm"
                  disabled={deliverMutation.isPending}
                  onClick={() =>
                    deliverMutation.mutate(existingPr?.pr_state === "closed")
                  }
                >
                  <GitPullRequest className="size-3.5" />
                  {deliverLabel}
                </Button>
              )}
            </div>
          )}

          {(files ?? []).map((file: DockerFilePublic) => {
            const fileFindings = findingsByFile.get(file.path) ?? []
            const fileFix = fixByFile.get(file.path)
            const fixInFlight = fileFix ? IN_FLIGHT.has(fileFix.status) : false
            const showFix =
              fileFix?.status === "ready" || fileFix?.status === "delivered"
            return (
              <div key={file.path} className="flex flex-col gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  {fileFix && (
                    <StatusPill
                      colorClass={fixStatusColor(fileFix.status)}
                      className="capitalize shrink-0"
                    >
                      {fileFix.status}
                    </StatusPill>
                  )}
                  {fileFix?.pr_url && (
                    <a
                      href={fileFix.pr_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-xs text-blue-600 dark:text-blue-400 hover:underline"
                    >
                      View PR
                    </a>
                  )}
                  {fileFindings.length > 0 && !fixInFlight && (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() =>
                        generateMutation.mutate(fileFindings.map((f) => f.id))
                      }
                    >
                      <Wand2 className="size-3.5" />
                      Generate fix
                    </Button>
                  )}
                </div>
                <FileViewer
                  path={file.path}
                  rawContent={file.raw_content}
                  // The API reports the kind, so the grammar is never
                  // re-derived from the filename here.
                  grammar={file.kind === "compose" ? "compose" : "dockerfile"}
                  fullContent={
                    showFix ? (fileFix?.full_content ?? undefined) : undefined
                  }
                  annotations={fileFindings}
                />
                {/* The viewer annotates findings inline, but a rule that fires
                    on the file as a whole (or past its last line) has no line
                    to hang off — listing them keeps every finding readable. */}
                {fileFindings.length > 0 && (
                  <div className="rounded-md border divide-y">
                    {fileFindings.map((finding) => (
                      <DockerFindingRow key={finding.id} finding={finding} />
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </CardContent>
      )}
    </Card>
  )
}
