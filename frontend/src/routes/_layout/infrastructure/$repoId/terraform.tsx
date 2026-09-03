import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { ChevronDown, ChevronRight, GitPullRequest } from "lucide-react"
import { useMemo, useState } from "react"
import type {
  PullRequestPublic,
  TerraformFilePublic,
  TerraformFindingPublic,
  TerraformFixPublic,
  TerraformRootPublic,
} from "@/client"
import { TerraformService, WorkflowService } from "@/client"
import { ConfirmRemoveDialog } from "@/components/ConfirmRemoveDialog"
import {
  EngineActionBar,
  EngineActionButton,
  overflowItem,
} from "@/components/EngineActionBar"
import { EngineFlowRail } from "@/components/EngineFlowRail"
import { FileViewer } from "@/components/FileViewer"
import { GradeBadge } from "@/components/GradeBadge"
import { ScanRunningBadge } from "@/components/ScanRunningBadge"
import { StatusPill } from "@/components/StatusPill"
import { TerraformFindingRow } from "@/components/TerraformFindingRow"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { useEngineTarget } from "@/hooks/useEngineTarget"
import { useOrgQuotas } from "@/hooks/useOrgQuotas"
import { useRepository } from "@/hooks/useRepository"
import { tfFixBranch } from "@/lib/delivery"
import {
  ALREADY_FIXED_REASON,
  engineActions,
  isSpentFix,
  type QuotaReasons,
  queueableFindings,
  removeAction,
} from "@/lib/engine-actions"
import { formatDateTime } from "@/lib/format"
import { isScanInFlight, pollForActivity } from "@/lib/scan-polling"
import {
  fixStatusColor,
  scanStatusColor,
  scanStatusLabel,
} from "@/lib/status-colors"

export const Route = createFileRoute(
  "/_layout/infrastructure/$repoId/terraform",
)({
  component: TerraformTab,
  head: () => ({
    meta: [{ title: "Terraform - GreenSecOps" }],
  }),
})

function TerraformTab() {
  const { repoId } = Route.useParams()
  const [openRoots, setOpenRoots] = useState<Set<string>>(new Set())
  const { repo, isAccessible } = useRepository(repoId)
  // What the owning org has left to spend. Scanning a root and writing its
  // fixes both draw on it, and a spent allowance is a 402 the button should
  // have shown coming.
  const quota = useOrgQuotas(repo?.org_id)

  const { data: roots, isLoading } = useQuery({
    queryKey: ["terraform-roots", "repo", repoId],
    queryFn: () => TerraformService.listRoots({ repoId }),
    // Follow a running scan to its end. The list carries every root's grade and
    // scan status, so re-asking for it is what turns "queued" into a result
    // without a page reload — and it stops the moment nothing is running.
    refetchInterval: (query) =>
      pollForActivity((query.state.data ?? []).map((root) => root.activity)),
  })

  const { data: pullRequests } = useQuery({
    queryKey: ["pull-requests", "repo", repoId],
    queryFn: () => WorkflowService.listPullRequests({ repoId }),
  })

  const prByBranch = useMemo(() => {
    const map = new Map<string, PullRequestPublic>()
    for (const pr of pullRequests ?? []) map.set(pr.pr_branch, pr)
    return map
  }, [pullRequests])

  function toggleOpen(rootId: string) {
    setOpenRoots((prev) => {
      const next = new Set(prev)
      next.has(rootId) ? next.delete(rootId) : next.add(rootId)
      return next
    })
  }

  if (isLoading) {
    return (
      <div className="flex flex-col gap-4">
        {[...Array(2)].map((_, i) => (
          <Skeleton key={i} className="h-32 w-full" />
        ))}
      </div>
    )
  }

  if (!roots?.length) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-muted-foreground text-sm">
          No Terraform roots configured for this repository. Add one from the{" "}
          <span className="font-medium">Infrastructure</span> list.
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      {roots.map((root) => (
        <RootCard
          key={root.id}
          root={root}
          isOpen={openRoots.has(root.id)}
          onToggleOpen={() => toggleOpen(root.id)}
          existingPr={prByBranch.get(tfFixBranch(root.id))}
          isAccessible={isAccessible}
          quota={quota}
        />
      ))}
    </div>
  )
}

interface RootCardProps {
  root: TerraformRootPublic
  isOpen: boolean
  onToggleOpen: () => void
  existingPr: PullRequestPublic | undefined
  isAccessible: boolean
  quota: QuotaReasons | undefined
}

function RootCard({
  root,
  isOpen,
  onToggleOpen,
  existingPr,
  isAccessible,
  quota,
}: RootCardProps) {
  const [historyOpen, setHistoryOpen] = useState(false)
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
  } = useEngineTarget<
    TerraformFilePublic,
    TerraformFindingPublic,
    TerraformFixPublic
  >(
    root.id,
    isOpen,
    {
      keyPrefix: "terraform",
      targetLabel: "Terraform root",
      listFiles: () => TerraformService.listFiles({ rootId: root.id }),
      listFindings: () => TerraformService.listFindings({ rootId: root.id }),
      listFixes: () => TerraformService.listFixes({ rootId: root.id }),
      toggle: (enabled) =>
        TerraformService.updateRoot({
          rootId: root.id,
          requestBody: { enabled },
        }),
      scan: () => TerraformService.triggerScan({ rootId: root.id }),
      remove: () => TerraformService.deleteRoot({ rootId: root.id }),
      generate: (findingIds, force) =>
        TerraformService.generateFixes({
          rootId: root.id,
          force,
          requestBody: findingIds.length ? { finding_ids: findingIds } : {},
        }),
      deliver: (force) =>
        TerraformService.deliverFixes({ rootId: root.id, force }),
    },
    isScanInFlight(root.latest_scan_status),
  )

  // Scan history is Terraform-only and loads on its own disclosure, so it stays
  // here rather than in the shared hook.
  const { data: scans } = useQuery({
    queryKey: ["terraform-scans", root.id],
    queryFn: () => TerraformService.listScans({ rootId: root.id }),
    enabled: isOpen && historyOpen,
  })

  const findingsByFile = useMemo(() => {
    const map = new Map<string, TerraformFindingPublic[]>()
    for (const f of findings ?? []) {
      const list = map.get(f.file_path) ?? []
      list.push(f)
      map.set(f.file_path, list)
    }
    return map
  }, [findings])

  const fixByFile = useMemo(() => {
    const map = new Map<string, TerraformFixPublic>()
    for (const fix of fixes ?? []) map.set(fix.file_path, fix)
    return map
  }, [fixes])

  const openFindings = (findings ?? []).filter(
    (f) => f.status !== "ignored" && f.status !== "resolved",
  )
  // Findings a plain "Generate fixes" would actually queue something for: the
  // route skips any file whose fix is already written, so counting every open
  // finding left the button live over a request that returned `queued: 0`.
  const queueable = queueableFindings(openFindings, fixByFile)
  const regenerable = (fixes ?? []).filter((f) => isSpentFix(f.status))

  // One description of what this root may do, shared by the header bar and by
  // each file's own button below — the difference between them is the scope,
  // not the rules.
  const rootState = {
    targetLabel: "Terraform root",
    isAccessible,
    enabled: root.enabled,
    quota,
    // The server's own answer, which knows about work this page did not start —
    // a scan the Action queued, a fix a teammate asked for. Unioned with the
    // statuses below rather than replacing them; see `targetActivity`.
    activity: root.activity,
    scanStatus: root.latest_scan_status,
    fixStatuses: (fixes ?? []).map((f) => f.status),
    existingPr,
  }
  const actions = engineActions({
    ...rootState,
    scope: "target" as const,
    openFindingCount: queueable.length,
    // Three different silences to break, in order of how wrong the default
    // would read: a root nobody has scanned has no findings *because* of that,
    // and "No open findings to fix" would read as "there is nothing wrong
    // here"; a root whose files all have fixes already is not clean either.
    noFindingsReason: !root.last_scanned_at
      ? "Scan this root first"
      : openFindings.length
        ? ALREADY_FIXED_REASON
        : undefined,
    pending: {
      scan: scanMutation.isPending,
      generate: generateMutation.isPending,
      deliver: deliverMutation.isPending,
    },
  })
  // Discarding every written fix and starting over: the way out of the state
  // the button above greys itself for. A menu item rather than a fourth
  // button, matching the CI page — it is deliberate and occasional.
  const regenerateAll = engineActions({
    ...rootState,
    scope: "target" as const,
    regenerate: true,
    openFindingCount: regenerable.length && openFindings.length ? 1 : 0,
    noFindingsReason: openFindings.length
      ? "No written fix to discard"
      : "No open findings to fix",
    pending: { generate: generateMutation.isPending },
  }).generate

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
            <span className="truncate min-w-0 flex-1">{root.root_path}</span>
            <GradeBadge
              grade={root.latest_grade ?? null}
              className="shrink-0"
            />
          </CardTitle>
          <EngineActionBar
            actions={actions}
            onScan={() => scanMutation.mutate()}
            onGenerate={() => generateMutation.mutate({ findingIds: [] })}
            onDeliver={() => deliverMutation.mutate(actions.deliver.force)}
            leading={
              <>
                <ScanRunningBadge status={root.latest_scan_status} />
                <div className="flex items-center gap-2">
                  <Switch
                    checked={root.enabled}
                    onCheckedChange={(enabled) =>
                      toggleMutation.mutate(enabled)
                    }
                    disabled={!isAccessible || toggleMutation.isPending}
                    aria-label="Enable this root"
                  />
                  <span className="text-xs text-muted-foreground">
                    {root.enabled ? "Enabled" : "Disabled"}
                  </span>
                </div>
              </>
            }
            overflow={[
              overflowItem(
                regenerateAll,
                () =>
                  generateMutation.mutate({
                    findingIds: openFindings.map((f) => f.id),
                    force: true,
                  }),
                { label: "Regenerate all fixes" },
              ),
              overflowItem(
                removeAction({
                  ...rootState,
                  scope: "target",
                  pending: { remove: deleteMutation.isPending },
                }),
                () => setConfirmRemove(true),
                { destructive: true },
              ),
            ]}
          />
        </div>
        <ConfirmRemoveDialog
          open={confirmRemove}
          onOpenChange={setConfirmRemove}
          name={root.root_path}
          targetLabel="Terraform root"
          onConfirm={() => deleteMutation.mutate()}
        />
        {root.last_scanned_at && (
          <p className="text-xs text-muted-foreground">
            Last scanned {formatDateTime(root.last_scanned_at)}
          </p>
        )}
      </CardHeader>

      {/* What this root is doing, and what each stage of its flow has to show
          for itself — above the files rather than only inside the tooltips on
          the bar. Drawn only when expanded: the collapsed header already
          carries the grade, the scan badge and the greyed buttons, and four
          more chips per collapsed card would bury them. */}
      {isOpen && (
        <CardContent className="flex flex-col gap-3">
          <EngineFlowRail
            {...rootState}
            scope="target"
            capabilities={{ sync: false }}
            fileCount={files?.length}
            grade={root.latest_grade}
            hasCompletedScan={!!root.last_scanned_at}
            openFindingCount={openFindings.length}
            pending={{
              scan: scanMutation.isPending,
              generate: generateMutation.isPending,
              deliver: deliverMutation.isPending,
            }}
          />
          {isLoading ? (
            <Skeleton className="h-40 w-full" />
          ) : !files?.length ? (
            <p className="text-sm text-muted-foreground py-4 text-center">
              No Terraform files found.
              {!root.last_scanned_at && " Run a scan to fetch this root."}
            </p>
          ) : (
            files.map((file) => {
              const fileFindings = findingsByFile.get(file.path) ?? []
              const fileFix = fixByFile.get(file.path)
              const showFix =
                fileFix?.status === "ready" || fileFix?.status === "delivered"
              const openIds = fileFindings
                .filter(
                  (f) => f.status !== "ignored" && f.status !== "resolved",
                )
                .map((f) => f.id)
              // Same rules, narrowed to this file: only its own fix counts as
              // in flight, so one file generating never freezes the rest. A
              // file whose fix is already written offers to discard and rewrite
              // it — a plain generate would queue nothing and say it had.
              const fileAction = engineActions({
                ...rootState,
                scope: "file" as const,
                regenerate: isSpentFix(fileFix?.status),
                fixStatuses: fileFix ? [fileFix.status] : [],
                openFindingCount: openIds.length,
                pending: { generate: generateMutation.isPending },
              }).generate
              return (
                <div key={file.path} className="flex flex-col gap-2">
                  <div className="flex items-center justify-between gap-2 flex-wrap">
                    <div className="flex items-center gap-2 min-w-0">
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
                          className="text-xs text-blue-600 dark:text-blue-400 hover:underline flex items-center gap-1 shrink-0"
                        >
                          <GitPullRequest className="h-3 w-3" />
                          View PR
                        </a>
                      )}
                    </div>
                    {/* Drawn whenever the file has findings at all, greyed
                        with its reason when they are all muted or resolved —
                        hiding it left "why can I not fix this?" unanswered. */}
                    {fileFindings.length > 0 && (
                      <EngineActionButton
                        action={fileAction}
                        onClick={() =>
                          generateMutation.mutate({
                            findingIds: openIds,
                            force: fileAction.force,
                          })
                        }
                        compact
                      />
                    )}
                  </div>
                  <FileViewer
                    path={file.path}
                    rawContent={file.raw_content}
                    grammar="hcl"
                    fullContent={
                      showFix ? (fileFix?.full_content ?? undefined) : undefined
                    }
                    annotations={fileFindings}
                  />
                  {/* The viewer annotates findings inline, but a rule that
                      fires on the module as a whole (or past its last line)
                      has no line to hang off — listing them keeps every
                      finding readable. */}
                  {fileFindings.length > 0 && (
                    <div className="rounded-md border divide-y">
                      {fileFindings.map((finding) => (
                        <TerraformFindingRow
                          key={finding.id}
                          finding={finding}
                          targetState={{ ...rootState, scope: "target" }}
                        />
                      ))}
                    </div>
                  )}
                </div>
              )
            })
          )}

          <div className="rounded-md border">
            <button
              type="button"
              onClick={() => setHistoryOpen((o) => !o)}
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
