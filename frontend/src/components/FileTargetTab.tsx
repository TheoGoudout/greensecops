import { useQuery } from "@tanstack/react-query"
import { ChevronDown, ChevronRight, GitPullRequest } from "lucide-react"
import { type ReactNode, useMemo, useState } from "react"
import type {
  FindingStatus,
  FixStatus,
  PullRequestPublic,
  ScanStatus,
  ScanTrigger,
  Severity,
  TargetActivity,
} from "@/client"
import { WorkflowService } from "@/client"
import { ConfirmRemoveDialog } from "@/components/ConfirmRemoveDialog"
import {
  EngineActionBar,
  EngineActionButton,
  overflowItem,
} from "@/components/EngineActionBar"
import { EngineFlowRail } from "@/components/EngineFlowRail"
import type { Annotation } from "@/components/FileViewer"
import { FileViewer } from "@/components/FileViewer"
import { GradeBadge } from "@/components/GradeBadge"
import { ScanRunningBadge } from "@/components/ScanRunningBadge"
import { StatusPill } from "@/components/StatusPill"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import {
  type EngineTargetCalls,
  useEngineTarget,
} from "@/hooks/useEngineTarget"
import { useOrgQuotas } from "@/hooks/useOrgQuotas"
import { useRepository } from "@/hooks/useRepository"
import {
  ALREADY_FIXED_REASON,
  type EngineActionInput,
  engineActions,
  isSpentFix,
  type QuotaReasons,
  queueableFindings,
  removeAction,
} from "@/lib/engine-actions"
import type { Grammar } from "@/lib/file-viewer"
import { formatDateTime } from "@/lib/format"
import { isScanInFlight, pollForActivity } from "@/lib/scan-polling"
import { severityRank } from "@/lib/severity"
import {
  fixStatusColor,
  scanStatusColor,
  scanStatusLabel,
} from "@/lib/status-colors"

/**
 * The analysis tab of a file engine — Terraform, Ansible, Docker — once.
 *
 * The three pages were the same screen written out three times: a list of the
 * repository's registered targets, each card expanding to its files with the
 * findings annotated inline and any written fix diffed against them, and the
 * same six actions. They had drifted only in wording and spacing. What
 * genuinely differs per engine is in {@link FileEngine}.
 */

/** A registered target, as every engine's `*Public` schema shapes it. */
export interface FileTarget {
  id: string
  root_path: string
  enabled: boolean
  last_scanned_at?: string | null
  latest_grade?: string | null
  latest_scan_status?: ScanStatus | null
  activity?: TargetActivity
}

export interface EngineFile {
  path: string
  raw_content: string
}

export interface EngineFinding extends Annotation {
  file_path: string
  status?: FindingStatus
  severity: Severity
}

export interface EngineFix {
  file_path: string
  status: FixStatus
  pr_url?: string | null
  full_content?: string | null
}

export interface EngineScan {
  id: string
  status: ScanStatus
  triggered_by: ScanTrigger
  grade?: string | null
  created_at?: string | null
}

/** What one file engine supplies to the shared tab. */
export interface FileEngine<
  TTarget extends FileTarget,
  TFile extends EngineFile,
  TFinding extends EngineFinding,
  TFix extends EngineFix,
> {
  /** Query-key prefix, e.g. `"terraform"`. */
  keyPrefix: string
  /** What a target is called, in full ("Terraform root") and on its own ("root"). */
  targetLabel: string
  noun: string
  /** "Terraform", for "No Terraform files found". */
  label: string
  /** Shown when the repository has no target registered. */
  empty: ReactNode
  /** The deterministic PR branch a target's fixes are delivered on. */
  fixBranch: (targetId: string) => string
  listTargets: (repoId: string) => Promise<TTarget[]>
  calls: (
    targetId: string,
  ) => Omit<
    EngineTargetCalls<TFile, TFinding, TFix>,
    "keyPrefix" | "targetLabel"
  >
  /** Omitted where the engine shows its scans on a tab of their own. */
  listScans?: (targetId: string) => Promise<EngineScan[]>
  grammarOf: (file: TFile) => Grammar
  /** A label for the file beside its path, when the engine classifies files. */
  kindOf?: (file: TFile) => string
  renderFinding: (
    finding: TFinding,
    targetState: EngineActionInput,
  ) => ReactNode
}

/** The query key of a repository's targets on one engine. */
export function targetsKey(keyPrefix: string, repoId?: string) {
  return repoId === undefined
    ? [`${keyPrefix}-targets`]
    : [`${keyPrefix}-targets`, "repo", repoId]
}

export function FileTargetTab<
  TTarget extends FileTarget,
  TFile extends EngineFile,
  TFinding extends EngineFinding,
  TFix extends EngineFix,
>({
  engine,
  repoId,
}: {
  engine: FileEngine<TTarget, TFile, TFinding, TFix>
  repoId: string
}) {
  const [open, setOpen] = useState<Set<string>>(new Set())
  const { repo, isAccessible } = useRepository(repoId)
  // What the owning org has left to spend. Scanning a target and writing its
  // fixes both draw on it, and a spent allowance is a 402 the button should
  // have shown coming.
  const quota = useOrgQuotas(repo?.org_id)

  const { data: targets, isLoading } = useQuery({
    queryKey: targetsKey(engine.keyPrefix, repoId),
    queryFn: () => engine.listTargets(repoId),
    // Follow a running scan to its end. The list carries every target's grade
    // and scan status, so re-asking for it is what turns "queued" into a
    // result without a page reload — and it stops once nothing is running.
    refetchInterval: (query) => pollForActivity(query.state.data ?? []),
  })

  // A ready fix carries no PR of its own, so whether one already exists for
  // its deterministic branch has to come from the real PullRequest rows.
  const { data: pullRequests } = useQuery({
    queryKey: ["pull-requests", "repo", repoId],
    queryFn: () => WorkflowService.listPullRequests({ repoId }),
  })
  const prByBranch = useMemo(() => {
    const map = new Map<string, PullRequestPublic>()
    for (const pr of pullRequests ?? []) map.set(pr.pr_branch, pr)
    return map
  }, [pullRequests])

  const toggleOpen = (id: string) =>
    setOpen((prev) => {
      const next = new Set(prev)
      if (!next.delete(id)) next.add(id)
      return next
    })

  if (isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-32 w-full" />
      </div>
    )
  }

  if (!targets?.length) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-muted-foreground text-sm">
          {engine.empty}
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      {targets.map((target) => (
        <TargetCard
          key={target.id}
          engine={engine}
          target={target}
          isOpen={open.has(target.id)}
          onToggleOpen={() => toggleOpen(target.id)}
          existingPr={prByBranch.get(engine.fixBranch(target.id))}
          isAccessible={isAccessible}
          quota={quota}
        />
      ))}
    </div>
  )
}

const isOpenFinding = (f: EngineFinding) =>
  f.status !== "ignored" && f.status !== "resolved"

/**
 * One registered target: its grade, its actions, and — once expanded — its
 * source with findings annotated inline and any generated fix diffed against it.
 */
function TargetCard<
  TTarget extends FileTarget,
  TFile extends EngineFile,
  TFinding extends EngineFinding,
  TFix extends EngineFix,
>({
  engine,
  target,
  isOpen,
  onToggleOpen,
  existingPr,
  isAccessible,
  quota,
}: {
  engine: FileEngine<TTarget, TFile, TFinding, TFix>
  target: TTarget
  isOpen: boolean
  onToggleOpen: () => void
  existingPr: PullRequestPublic | undefined
  isAccessible: boolean
  quota: QuotaReasons | undefined
}) {
  const [confirmRemove, setConfirmRemove] = useState(false)
  const { noun, targetLabel } = engine
  const name = target.root_path || "/ (repository root)"

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
  } = useEngineTarget<TFile, TFinding, TFix>(
    target.id,
    isOpen,
    {
      keyPrefix: engine.keyPrefix,
      targetLabel,
      ...engine.calls(target.id),
    },
    isScanInFlight(target.latest_scan_status),
  )

  // Most severe first within each file: the list under a file is read top down.
  const findingsByFile = useMemo(() => {
    const map = new Map<string, TFinding[]>()
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

  const fixByFile = useMemo(() => {
    const map = new Map<string, TFix>()
    for (const fix of fixes ?? []) map.set(fix.file_path, fix)
    return map
  }, [fixes])

  const openFindings = (findings ?? []).filter(isOpenFinding)
  // Findings a plain "Generate fixes" would actually queue something for: the
  // route skips any file whose fix is already written, so counting every open
  // finding left the button live over a request that returned `queued: 0`.
  const queueable = queueableFindings(openFindings, fixByFile)
  const regenerable = (fixes ?? []).filter((f) => isSpentFix(f.status))

  // One description of what this target may do, shared by the header bar and
  // by each file's own button below — the difference between them is the
  // scope, not the rules.
  const targetState = {
    targetLabel,
    isAccessible,
    enabled: target.enabled,
    quota,
    // The server's own answer, which knows about work this page did not start
    // — a scan the Action queued, a fix a teammate asked for. Unioned with the
    // statuses below rather than replacing them; see `targetActivity`.
    activity: target.activity,
    scanStatus: target.latest_scan_status,
    fixStatuses: (fixes ?? []).map((f) => f.status),
    existingPr,
  }
  const pending = {
    scan: scanMutation.isPending,
    generate: generateMutation.isPending,
    deliver: deliverMutation.isPending,
  }
  const actions = engineActions({
    ...targetState,
    scope: "target" as const,
    openFindingCount: queueable.length,
    // Two silences to break: a target nobody has scanned has no findings
    // *because* of that, and "No open findings to fix" would read as "nothing
    // is wrong here"; a target whose files all have fixes is not clean either.
    noFindingsReason: !target.last_scanned_at
      ? `Scan this ${noun} first`
      : openFindings.length
        ? ALREADY_FIXED_REASON
        : undefined,
    pending,
  })
  // Discarding every written fix and starting over: the way out of the state
  // the button above greys itself for. A menu item rather than a fourth
  // button, matching the CI page — it is deliberate and occasional.
  const regenerateAll = engineActions({
    ...targetState,
    scope: "target" as const,
    regenerate: true,
    openFindingCount: regenerable.length && openFindings.length ? 1 : 0,
    noFindingsReason: openFindings.length
      ? "No written fix to discard"
      : "No open findings to fix",
    pending: { generate: generateMutation.isPending },
  }).generate

  const expandLabel = `${isOpen ? "Collapse" : "Expand"} ${noun}`

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
              aria-label={expandLabel}
              title={expandLabel}
            >
              {isOpen ? (
                <ChevronDown className="h-4 w-4" />
              ) : (
                <ChevronRight className="h-4 w-4" />
              )}
            </button>
            <span className="truncate min-w-0 flex-1">{name}</span>
            <GradeBadge
              grade={target.latest_grade ?? null}
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
                <ScanRunningBadge status={target.latest_scan_status} />
                <div className="flex items-center gap-2">
                  <Switch
                    checked={target.enabled}
                    onCheckedChange={(enabled) =>
                      toggleMutation.mutate(enabled)
                    }
                    disabled={!isAccessible || toggleMutation.isPending}
                    aria-label={`Enable this ${noun}`}
                  />
                  <span className="text-xs text-muted-foreground">
                    {target.enabled ? "Enabled" : "Disabled"}
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
                  ...targetState,
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
          name={target.root_path || "/"}
          targetLabel={targetLabel}
          onConfirm={() => deleteMutation.mutate()}
        />
        <p className="text-xs text-muted-foreground">
          {target.last_scanned_at
            ? `Last scanned ${formatDateTime(target.last_scanned_at)}`
            : "Never scanned"}
        </p>
      </CardHeader>

      {/* What this target is doing, and what each stage of its flow has to
          show for itself — above the files rather than only inside the
          tooltips on the bar. Drawn only when expanded: the collapsed header
          already carries the grade, the scan badge and the greyed buttons. */}
      {isOpen && (
        <CardContent className="flex flex-col gap-3">
          <EngineFlowRail
            {...targetState}
            scope="target"
            capabilities={{ sync: false }}
            fileCount={files?.length}
            grade={target.latest_grade}
            hasCompletedScan={!!target.last_scanned_at}
            openFindingCount={openFindings.length}
            pending={pending}
          />
          {isLoading ? (
            <Skeleton className="h-40 w-full" />
          ) : !files?.length ? (
            <p className="text-sm text-muted-foreground py-4 text-center">
              No {engine.label} files found under this path.
              {!target.last_scanned_at && ` Run a scan to fetch this ${noun}.`}
            </p>
          ) : (
            files.map((file) => {
              const fileFindings = findingsByFile.get(file.path) ?? []
              const fileFix = fixByFile.get(file.path)
              const showFix =
                fileFix?.status === "ready" || fileFix?.status === "delivered"
              const openIds = fileFindings
                .filter(isOpenFinding)
                .map((f) => f.id)
              // Same rules, narrowed to this file: only its own fix counts as
              // in flight, so one file generating never freezes the rest. A
              // file whose fix is already written offers to discard and
              // rewrite it — a plain generate would queue nothing.
              const fileAction = engineActions({
                ...targetState,
                scope: "file" as const,
                regenerate: isSpentFix(fileFix?.status),
                fixStatuses: fileFix ? [fileFix.status] : [],
                openFindingCount: openIds.length,
                pending: { generate: generateMutation.isPending },
              }).generate
              const kind = engine.kindOf?.(file)
              return (
                <div key={file.path} className="flex flex-col gap-2">
                  <div className="flex items-center justify-between gap-2 flex-wrap">
                    <div className="flex items-center gap-2 min-w-0">
                      {kind && (
                        <StatusPill
                          colorClass="bg-muted text-muted-foreground"
                          className="shrink-0"
                        >
                          {kind}
                        </StatusPill>
                      )}
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
                          className="text-xs text-info-ink hover:underline flex items-center gap-1 shrink-0"
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
                    grammar={engine.grammarOf(file)}
                    fullContent={
                      showFix ? (fileFix?.full_content ?? undefined) : undefined
                    }
                    annotations={fileFindings}
                  />
                  {/* The viewer annotates findings inline, but a rule that
                      fires on the file as a whole (or past its last line) has
                      no line to hang off — listing them keeps every finding
                      readable. */}
                  {fileFindings.length > 0 && (
                    <div className="rounded-md border divide-y">
                      {fileFindings.map((finding) => (
                        <div key={finding.id}>
                          {engine.renderFinding(finding, {
                            ...targetState,
                            scope: "target",
                          })}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )
            })
          )}
          {engine.listScans && (
            <ScanHistory
              queryKey={[`${engine.keyPrefix}-scans`, target.id]}
              listScans={() =>
                engine.listScans?.(target.id) ?? Promise.resolve([])
              }
            />
          )}
        </CardContent>
      )}
    </Card>
  )
}

/** A target's past scans, loaded only once its disclosure is opened. */
function ScanHistory({
  queryKey,
  listScans,
}: {
  queryKey: unknown[]
  listScans: () => Promise<EngineScan[]>
}) {
  const [open, setOpen] = useState(false)
  const { data: scans } = useQuery({
    queryKey,
    queryFn: listScans,
    enabled: open,
  })

  return (
    <div className="rounded-md border">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-4 py-2 text-left text-xs font-medium text-muted-foreground hover:bg-muted/40 transition-colors"
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5" />
        )}
        Scan history
      </button>
      {open && (
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
                  {formatDateTime(scan.created_at)}
                </span>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}
