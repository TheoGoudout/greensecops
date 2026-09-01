import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import {
  ChevronDown,
  ChevronRight,
  GitPullRequest,
  Loader2,
  Play,
  Trash2,
  Wand2,
  Zap,
} from "lucide-react"
import { useMemo, useState } from "react"
import type {
  PullRequestPublic,
  TerraformFilePublic,
  TerraformFindingPublic,
  TerraformFixPublic,
  TerraformRootPublic,
} from "@/client"
import { TerraformService, WorkflowService } from "@/client"
import { FileViewer } from "@/components/FileViewer"
import { GradeBadge } from "@/components/GradeBadge"
import { ScanRunningBadge } from "@/components/ScanRunningBadge"
import { StatusPill } from "@/components/StatusPill"
import { TerraformFindingRow } from "@/components/TerraformFindingRow"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { useEngineTarget } from "@/hooks/useEngineTarget"
import { tfFixBranch } from "@/lib/delivery"
import { formatDateTime } from "@/lib/format"
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

// Fix statuses a worker is actively processing — used to disable actions.
const IN_FLIGHT = new Set(["pending", "generating", "delivering"])

function TerraformTab() {
  const { repoId } = Route.useParams()
  const [openRoots, setOpenRoots] = useState<Set<string>>(new Set())

  const { data: roots, isLoading } = useQuery({
    queryKey: ["terraform-roots", "repo", repoId],
    queryFn: () => TerraformService.listRoots({ repoId }),
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
}

function RootCard({ root, isOpen, onToggleOpen, existingPr }: RootCardProps) {
  const [historyOpen, setHistoryOpen] = useState(false)

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
  >(root.id, isOpen, {
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
    generate: (findingIds) =>
      TerraformService.generateFixes({
        rootId: root.id,
        requestBody: findingIds.length ? { finding_ids: findingIds } : {},
      }),
    deliver: (force) =>
      TerraformService.deliverFixes({ rootId: root.id, force }),
  })

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

  const openFindingCount = (findings ?? []).filter(
    (f) => f.status !== "ignored" && f.status !== "resolved",
  ).length
  const hasReadyFix = (fixes ?? []).some((f) => f.status === "ready")
  const prState = existingPr?.pr_state
  const deliverLabel =
    prState === "closed" ? "Reopen PR" : existingPr ? "Update PR" : "Create PR"

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
          <div className="flex items-center gap-3 shrink-0">
            <ScanRunningBadge status={root.latest_scan_status} />
            <div className="flex items-center gap-2">
              <Switch
                checked={root.enabled}
                onCheckedChange={(enabled) => toggleMutation.mutate(enabled)}
                disabled={toggleMutation.isPending}
              />
              <span className="text-xs text-muted-foreground">
                {root.enabled ? "Enabled" : "Disabled"}
              </span>
            </div>
            <Button
              size="sm"
              variant="ghost"
              className="h-7 text-xs gap-1.5"
              onClick={() => scanMutation.mutate()}
              disabled={!root.enabled || scanMutation.isPending}
              title={
                root.enabled ? "Scan this root now" : "Enable this root to scan"
              }
            >
              {scanMutation.isPending ? (
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
              onClick={() => {
                if (
                  window.confirm(
                    `Remove Terraform root "${root.root_path}"? This deletes its scan history, findings and fixes.`,
                  )
                ) {
                  deleteMutation.mutate()
                }
              }}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending ? (
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
            Last scanned {formatDateTime(root.last_scanned_at)}
          </p>
        )}
      </CardHeader>

      {isOpen && (
        <CardContent className="flex flex-col gap-3">
          <div className="flex items-center gap-2 flex-wrap">
            {openFindingCount > 0 && (
              <Button
                size="sm"
                variant="outline"
                className="h-7 text-xs gap-1.5"
                onClick={() => generateMutation.mutate([])}
                disabled={!root.enabled || generateMutation.isPending}
              >
                {generateMutation.isPending ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <Zap className="h-3 w-3" />
                )}
                Generate all fixes
              </Button>
            )}
            {hasReadyFix && (
              <Button
                size="sm"
                variant="outline"
                className="h-7 text-xs gap-1.5"
                onClick={() => deliverMutation.mutate(prState === "closed")}
                disabled={!root.enabled || deliverMutation.isPending}
              >
                {deliverMutation.isPending ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <GitPullRequest className="h-3 w-3" />
                )}
                {deliverLabel}
              </Button>
            )}
          </div>

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
              const fixInFlight = fileFix
                ? IN_FLIGHT.has(fileFix.status)
                : false
              const openIds = fileFindings
                .filter(
                  (f) => f.status !== "ignored" && f.status !== "resolved",
                )
                .map((f) => f.id)
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
                    {openIds.length > 0 && (
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 text-xs gap-1.5"
                        onClick={() => generateMutation.mutate(openIds)}
                        disabled={
                          !root.enabled ||
                          fixInFlight ||
                          generateMutation.isPending
                        }
                      >
                        {fixInFlight ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : (
                          <Wand2 className="h-3 w-3" />
                        )}
                        {fixInFlight ? "Generating…" : "Generate fix"}
                      </Button>
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
