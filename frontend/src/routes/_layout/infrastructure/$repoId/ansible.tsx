import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { ChevronDown, ChevronRight, GitPullRequest } from "lucide-react"
import { useMemo, useState } from "react"
import type {
  AnsibleFilePublic,
  AnsibleFindingPublic,
  AnsibleFixPublic,
  AnsibleProjectPublic,
  PullRequestPublic,
} from "@/client"
import { AnsibleService, WorkflowService } from "@/client"
import { AnsibleFindingRow } from "@/components/AnsibleFindingRow"
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
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { useEngineTarget } from "@/hooks/useEngineTarget"
import { useOrgQuotas } from "@/hooks/useOrgQuotas"
import { useRepository } from "@/hooks/useRepository"
import { ansibleFixBranch } from "@/lib/delivery"
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
import { fixStatusColor } from "@/lib/status-colors"

export const Route = createFileRoute("/_layout/infrastructure/$repoId/ansible")(
  {
    component: AnsibleTab,
    head: () => ({
      meta: [{ title: "Ansible - GreenSecOps" }],
    }),
  },
)

function AnsibleTab() {
  const { repoId } = Route.useParams()
  const [open, setOpen] = useState<Set<string>>(new Set())
  const { repo, isAccessible } = useRepository(repoId)
  // See terraform.tsx: scanning a project and writing its fixes both draw on
  // the org's allowance, and a spent one is a 402 worth showing coming.
  const quota = useOrgQuotas(repo?.org_id)

  const { data: projects, isLoading } = useQuery({
    queryKey: ["ansible-projects", "repo", repoId],
    queryFn: () => AnsibleService.listProjects({ repoId }),
    // See terraform.tsx: these engines publish no live events, so the list
    // polls itself while any scan is unfinished and stops when none is.
    refetchInterval: (query) =>
      pollForActivity(
        (query.state.data ?? []).map((project) => project.activity),
      ),
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

  if (isLoading) {
    return <Skeleton className="h-40 w-full" />
  }

  if (!projects?.length) {
    return (
      <Card>
        <CardContent className="py-10 text-center text-muted-foreground">
          <p>No Ansible projects registered for this repository.</p>
          <p className="mt-1 text-sm">
            Register one from the Infrastructure page to start grading its
            playbooks and roles.
          </p>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      {projects.map((project) => (
        <ProjectCard
          key={project.id}
          project={project}
          isOpen={open.has(project.id)}
          existingPr={prByBranch.get(ansibleFixBranch(project.id))}
          isAccessible={isAccessible}
          quota={quota}
          onToggleOpen={() =>
            setOpen((prev) => {
              const next = new Set(prev)
              next.has(project.id)
                ? next.delete(project.id)
                : next.add(project.id)
              return next
            })
          }
        />
      ))}
    </div>
  )
}

/**
 * One registered project: its grade, its actions, and — once expanded — its
 * source with findings annotated inline and any generated fix diffed against it.
 */
function ProjectCard({
  project,
  isOpen,
  existingPr,
  onToggleOpen,
  isAccessible,
  quota,
}: {
  project: AnsibleProjectPublic
  isOpen: boolean
  existingPr: PullRequestPublic | undefined
  onToggleOpen: () => void
  isAccessible: boolean
  quota: QuotaReasons | undefined
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
  } = useEngineTarget<
    AnsibleFilePublic,
    AnsibleFindingPublic,
    AnsibleFixPublic
  >(
    project.id,
    isOpen,
    {
      keyPrefix: "ansible",
      targetLabel: "Ansible project",
      listFiles: () => AnsibleService.listFiles({ projectId: project.id }),
      listFindings: () =>
        AnsibleService.listFindings({ projectId: project.id }),
      listFixes: () => AnsibleService.listFixes({ projectId: project.id }),
      toggle: (enabled) =>
        AnsibleService.updateProject({
          projectId: project.id,
          requestBody: { enabled },
        }),
      scan: () => AnsibleService.triggerScan({ projectId: project.id }),
      remove: () => AnsibleService.deleteProject({ projectId: project.id }),
      generate: (findingIds, force) =>
        AnsibleService.generateFixes({
          projectId: project.id,
          force,
          requestBody: findingIds.length ? { finding_ids: findingIds } : {},
        }),
      deliver: (force) =>
        AnsibleService.deliverFixes({ projectId: project.id, force }),
    },
    isScanInFlight(project.latest_scan_status),
  )

  const findingsByFile = useMemo(() => {
    const map = new Map<string, AnsibleFindingPublic[]>()
    for (const finding of findings ?? []) {
      const list = map.get(finding.file_path) ?? []
      list.push(finding)
      map.set(finding.file_path, list)
    }
    return map
  }, [findings])

  const fixByFile = useMemo(() => {
    const map = new Map<string, AnsibleFixPublic>()
    for (const fix of fixes ?? []) map.set(fix.file_path, fix)
    return map
  }, [fixes])

  const openFindings = (findings ?? []).filter(
    (f) => f.status !== "ignored" && f.status !== "resolved",
  )
  // See terraform.tsx: the route skips a file whose fix is already written, so
  // only these would actually queue anything.
  const queueable = queueableFindings(openFindings, fixByFile)
  const regenerable = (fixes ?? []).filter((f) => isSpentFix(f.status))

  // See terraform.tsx: one description of the project's state, read by the
  // header bar and by each file's own button at a narrower scope.
  const projectState = {
    targetLabel: "Ansible project",
    isAccessible,
    enabled: project.enabled,
    quota,
    // The server's own answer, which knows about work this page did not start
    // — a scan the Action queued, a fix a teammate asked for. Unioned with the
    // statuses below rather than replacing them; see `targetActivity`.
    activity: project.activity,
    scanStatus: project.latest_scan_status,
    fixStatuses: (fixes ?? []).map((f) => f.status),
    existingPr,
  }
  const actions = engineActions({
    ...projectState,
    scope: "target" as const,
    openFindingCount: queueable.length,
    noFindingsReason: !project.last_scanned_at
      ? "Scan this project first"
      : openFindings.length
        ? ALREADY_FIXED_REASON
        : undefined,
    pending: {
      scan: scanMutation.isPending,
      generate: generateMutation.isPending,
      deliver: deliverMutation.isPending,
    },
  })
  const regenerateAll = engineActions({
    ...projectState,
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
              title={isOpen ? "Collapse project" : "Expand project"}
            >
              {isOpen ? (
                <ChevronDown className="h-4 w-4" />
              ) : (
                <ChevronRight className="h-4 w-4" />
              )}
            </button>
            {/* "" is a legal root_path meaning the repository root. */}
            <span className="truncate min-w-0 flex-1">
              {project.root_path || "/"}
            </span>
            <GradeBadge
              grade={project.latest_grade ?? null}
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
                <ScanRunningBadge status={project.latest_scan_status} />
                <div className="flex items-center gap-2">
                  <Switch
                    checked={project.enabled}
                    onCheckedChange={(enabled) =>
                      toggleMutation.mutate(enabled)
                    }
                    disabled={!isAccessible || toggleMutation.isPending}
                    aria-label="Enable scanning for this project"
                  />
                  <span className="text-xs text-muted-foreground">
                    {project.enabled ? "Enabled" : "Disabled"}
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
                  ...projectState,
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
          name={project.root_path || "/"}
          targetLabel="Ansible project"
          onConfirm={() => deleteMutation.mutate()}
        />
        {project.last_scanned_at && (
          <p className="text-xs text-muted-foreground">
            Last scanned {formatDateTime(project.last_scanned_at)}
          </p>
        )}
      </CardHeader>

      {/* What this target is doing, and what each stage of its flow has to
          show for itself — above the files rather than only in the tooltips on
          the bar. Expanded only: the collapsed header already carries the
          grade, the scan badge and the greyed buttons. */}
      {isOpen && (
        <CardContent className="flex flex-col gap-3">
          <EngineFlowRail
            {...projectState}
            scope="target"
            capabilities={{ sync: false }}
            fileCount={files?.length}
            grade={project.latest_grade}
            hasCompletedScan={!!project.last_scanned_at}
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
              No Ansible files found under this path.
              {!project.last_scanned_at && " Run a scan to fetch this project."}
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
              // See terraform.tsx: a file whose fix is already written offers
              // to discard and rewrite it, because a plain generate would queue
              // nothing and say it had.
              const fileAction = engineActions({
                ...projectState,
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
                      {/* The classifier's label: a playbook reads differently
                          from a vars file, and the path alone doesn't say. */}
                      <StatusPill
                        colorClass="bg-muted text-muted-foreground"
                        className="shrink-0"
                      >
                        {file.kind}
                      </StatusPill>
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
                    // Every kind this engine reads is YAML — playbooks, task
                    // files, variables and galaxy requirements alike — so the
                    // classifier's `kind` labels the file rather than picking
                    // a grammar.
                    grammar="yaml"
                    rawContent={file.raw_content}
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
                        <AnsibleFindingRow
                          key={finding.id}
                          finding={finding}
                          targetState={{ ...projectState, scope: "target" }}
                        />
                      ))}
                    </div>
                  )}
                </div>
              )
            })
          )}
        </CardContent>
      )}
    </Card>
  )
}
