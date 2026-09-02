import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { ChevronDown, ChevronRight, Trash2 } from "lucide-react"
import { useMemo, useState } from "react"
import type {
  DockerFilePublic,
  DockerFindingPublic,
  DockerFixPublic,
  DockerTargetPublic,
  PullRequestPublic,
} from "@/client"
import { DockerService, WorkflowService } from "@/client"
import { ConfirmRemoveDialog } from "@/components/ConfirmRemoveDialog"
import { DockerFindingRow } from "@/components/DockerFindingRow"
import {
  EngineActionBar,
  EngineActionButton,
} from "@/components/EngineActionBar"
import { FileViewer } from "@/components/FileViewer"
import { GradeBadge } from "@/components/GradeBadge"
import { ScanRunningBadge } from "@/components/ScanRunningBadge"
import { StatusPill } from "@/components/StatusPill"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { useEngineTarget } from "@/hooks/useEngineTarget"
import { useRepository } from "@/hooks/useRepository"
import { dockerFixBranch } from "@/lib/delivery"
import { engineActions } from "@/lib/engine-actions"
import { isScanInFlight, pollWhileScanning } from "@/lib/scan-polling"
import { severityRank } from "@/lib/severity"
import { fixStatusColor } from "@/lib/status-colors"

export const Route = createFileRoute("/_layout/docker/$repoId/analysis")({
  component: DockerAnalysisTab,
  head: () => ({
    meta: [{ title: "Docker analysis - GreenSecOps" }],
  }),
})

function DockerAnalysisTab() {
  const { repoId } = Route.useParams()
  const [openTargets, setOpenTargets] = useState<Set<string>>(new Set())
  const { isAccessible } = useRepository(repoId)

  const { data: targets, isLoading } = useQuery({
    queryKey: ["docker-targets", "repo", repoId],
    queryFn: () => DockerService.listTargets({ repoId }),
    // See terraform.tsx: these engines publish no live events, so the list
    // polls itself while any scan is unfinished and stops when none is.
    refetchInterval: (query) =>
      pollWhileScanning(
        (query.state.data ?? []).map((target) => target.latest_scan_status),
      ),
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
          isAccessible={isAccessible}
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
  isAccessible,
}: {
  target: DockerTargetPublic
  isOpen: boolean
  onToggleOpen: () => void
  existingPr?: PullRequestPublic
  isAccessible: boolean
}) {
  const [confirmRemove, setConfirmRemove] = useState(false)
  const {
    files,
    isLoading,
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
    isScanInFlight(target.latest_scan_status),
  )

  const fixByFile = useMemo(() => {
    const map = new Map<string, DockerFixPublic>()
    for (const fix of fixes ?? []) map.set(fix.file_path, fix)
    return map
  }, [fixes])

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

  // Findings the engine reports as still open — the same filter the other file
  // engines apply. Docker counted every row, including ignored ones, which is
  // why its "Generate all fixes" button could offer to fix nothing.
  const openFindingCount = (findings ?? []).filter(
    (f) => f.status !== "ignored" && f.status !== "resolved",
  ).length

  // See terraform.tsx: one description of this target's state, read by the
  // header bar and by each file's own button at a narrower scope.
  const targetState = {
    targetLabel: "Docker target",
    isAccessible,
    enabled: target.enabled,
    scanStatus: target.latest_scan_status,
    fixStatuses: (fixes ?? []).map((f) => f.status),
    existingPr,
  }
  const actions = engineActions({
    ...targetState,
    scope: "target" as const,
    openFindingCount,
    // A target nobody has scanned yet has no findings *because* of that, and
    // "No open findings to fix" reads as "there is nothing wrong here".
    noFindingsReason: target.last_scanned_at
      ? undefined
      : "Scan this target first",
    pending: {
      scan: scanMutation.isPending,
      generate: generateMutation.isPending,
      deliver: deliverMutation.isPending,
    },
  })

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

        <EngineActionBar
          actions={actions}
          onScan={() => scanMutation.mutate()}
          onGenerate={() => generateMutation.mutate([])}
          onDeliver={() => deliverMutation.mutate(actions.deliver.force)}
          leading={
            <>
              <ScanRunningBadge status={target.latest_scan_status} />
              <GradeBadge grade={target.latest_grade ?? null} />
              <Switch
                checked={target.enabled}
                onCheckedChange={() => toggleMutation.mutate(!target.enabled)}
                disabled={!isAccessible || toggleMutation.isPending}
                aria-label="Enable target"
              />
            </>
          }
          overflow={[
            {
              label: "Remove",
              icon: Trash2,
              destructive: true,
              disabled: deleteMutation.isPending,
              onSelect: () => setConfirmRemove(true),
            },
          ]}
        />
        <ConfirmRemoveDialog
          open={confirmRemove}
          onOpenChange={setConfirmRemove}
          name={target.root_path || "/"}
          targetLabel="Docker target"
          onConfirm={() => deleteMutation.mutate()}
        />
      </CardHeader>

      {isOpen && (
        <CardContent className="flex flex-col gap-4">
          {isLoading && <Skeleton className="h-40 w-full" />}

          {(files ?? []).map((file: DockerFilePublic) => {
            const fileFindings = findingsByFile.get(file.path) ?? []
            const fileFix = fixByFile.get(file.path)
            const showFix =
              fileFix?.status === "ready" || fileFix?.status === "delivered"
            const openIds = fileFindings
              .filter((f) => f.status !== "ignored" && f.status !== "resolved")
              .map((f) => f.id)
            const fileAction = engineActions({
              ...targetState,
              scope: "file" as const,
              fixStatuses: fileFix ? [fileFix.status] : [],
              openFindingCount: openIds.length,
              pending: { generate: generateMutation.isPending },
            }).generate
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
                  {openIds.length > 0 && (
                    <EngineActionButton
                      action={fileAction}
                      onClick={() => generateMutation.mutate(openIds)}
                      compact
                    />
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
