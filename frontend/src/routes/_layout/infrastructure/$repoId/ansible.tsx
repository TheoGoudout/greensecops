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
  AnsibleFilePublic,
  AnsibleFindingPublic,
  AnsibleFixPublic,
  AnsibleProjectPublic,
  PullRequestPublic,
} from "@/client"
import { AnsibleService, WorkflowService } from "@/client"
import { FileViewer } from "@/components/FileViewer"
import { GradeBadge } from "@/components/GradeBadge"
import { ScanRunningBadge } from "@/components/ScanRunningBadge"
import { StatusPill } from "@/components/StatusPill"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { useEngineTarget } from "@/hooks/useEngineTarget"
import { ansibleFixBranch } from "@/lib/delivery"
import { formatDateTime } from "@/lib/format"
import { fixStatusColor } from "@/lib/status-colors"

export const Route = createFileRoute("/_layout/infrastructure/$repoId/ansible")(
  {
    component: AnsibleTab,
    head: () => ({
      meta: [{ title: "Ansible - GreenSecOps" }],
    }),
  },
)

// Fix statuses a worker is actively processing — used to disable actions.
const IN_FLIGHT = new Set(["pending", "generating", "delivering"])

function AnsibleTab() {
  const { repoId } = Route.useParams()
  const [open, setOpen] = useState<Set<string>>(new Set())

  const { data: projects, isLoading } = useQuery({
    queryKey: ["ansible-projects", "repo", repoId],
    queryFn: () => AnsibleService.listProjects({ repoId }),
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
}: {
  project: AnsibleProjectPublic
  isOpen: boolean
  existingPr: PullRequestPublic | undefined
  onToggleOpen: () => void
}) {
  const {
    files,
    filesLoading,
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
  >(project.id, isOpen, {
    keyPrefix: "ansible",
    targetLabel: "Ansible project",
    listFiles: () => AnsibleService.listFiles({ projectId: project.id }),
    listFindings: () => AnsibleService.listFindings({ projectId: project.id }),
    listFixes: () => AnsibleService.listFixes({ projectId: project.id }),
    toggle: (enabled) =>
      AnsibleService.updateProject({
        projectId: project.id,
        requestBody: { enabled },
      }),
    scan: () => AnsibleService.triggerScan({ projectId: project.id }),
    remove: () => AnsibleService.deleteProject({ projectId: project.id }),
    generate: (findingIds) =>
      AnsibleService.generateFixes({
        projectId: project.id,
        requestBody: findingIds.length ? { finding_ids: findingIds } : {},
      }),
    deliver: (force) =>
      AnsibleService.deliverFixes({ projectId: project.id, force }),
  })

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
          <div className="flex items-center gap-3 shrink-0">
            <ScanRunningBadge status={project.latest_scan_status} />
            <div className="flex items-center gap-2">
              <Switch
                checked={project.enabled}
                onCheckedChange={(enabled) => toggleMutation.mutate(enabled)}
                disabled={toggleMutation.isPending}
                aria-label="Enable scanning for this project"
              />
              <span className="text-xs text-muted-foreground">
                {project.enabled ? "Enabled" : "Disabled"}
              </span>
            </div>
            <Button
              size="sm"
              variant="ghost"
              className="h-7 text-xs gap-1.5"
              onClick={() => scanMutation.mutate()}
              disabled={!project.enabled || scanMutation.isPending}
              title={
                project.enabled
                  ? "Scan this project now"
                  : "Enable this project to scan"
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
                    `Remove Ansible project "${project.root_path || "/"}"? This deletes its scan history, findings and fixes.`,
                  )
                ) {
                  deleteMutation.mutate()
                }
              }}
              disabled={deleteMutation.isPending}
              aria-label="Remove this project"
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
        {project.last_scanned_at && (
          <p className="text-xs text-muted-foreground">
            Last scanned {formatDateTime(project.last_scanned_at)}
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
                disabled={!project.enabled || generateMutation.isPending}
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
                disabled={!project.enabled || deliverMutation.isPending}
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

          {filesLoading ? (
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
                    {openIds.length > 0 && (
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 text-xs gap-1.5"
                        onClick={() => generateMutation.mutate(openIds)}
                        disabled={
                          !project.enabled ||
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
                </div>
              )
            })
          )}
        </CardContent>
      )}
    </Card>
  )
}
