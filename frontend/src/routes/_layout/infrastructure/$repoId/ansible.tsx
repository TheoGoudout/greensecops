import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { ChevronDown, ChevronRight, Loader2, Play, Trash2 } from "lucide-react"
import { useMemo, useState } from "react"
import { toast } from "sonner"
import type { AnsibleFindingPublic, AnsibleProjectPublic } from "@/client"
import { AnsibleService } from "@/client"
import { AnsibleFindingRow } from "@/components/AnsibleFindingRow"
import { FileViewer } from "@/components/FileViewer"
import { GradeBadge } from "@/components/GradeBadge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { apiErrorDetail } from "@/lib/api-error"
import { formatDateTime } from "@/lib/format"

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

  const { data: projects, isLoading } = useQuery({
    queryKey: ["ansible-projects", "repo", repoId],
    queryFn: () => AnsibleService.listAnsibleProjects({ repoId }),
  })

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
          repoId={repoId}
          isOpen={open.has(project.id)}
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
 * source with findings annotated inline.
 *
 * Deliberately not built on `useEngineTarget`: that hook's contract includes
 * fix generation and delivery, which this engine does not have endpoints for
 * yet. It adopts the hook when those land, rather than passing stubs for half
 * of it now.
 */
function ProjectCard({
  project,
  repoId,
  isOpen,
  onToggleOpen,
}: {
  project: AnsibleProjectPublic
  repoId: string
  isOpen: boolean
  onToggleOpen: () => void
}) {
  const queryClient = useQueryClient()

  const invalidate = () =>
    queryClient.invalidateQueries({
      queryKey: ["ansible-projects", "repo", repoId],
    })

  const { data: files } = useQuery({
    queryKey: ["ansible-files", project.id],
    queryFn: () => AnsibleService.listAnsibleFiles({ projectId: project.id }),
    enabled: isOpen,
  })

  const { data: findings } = useQuery({
    queryKey: ["ansible-findings", project.id],
    queryFn: () =>
      AnsibleService.listAnsibleFindings({ projectId: project.id }),
    enabled: isOpen,
  })

  const scan = useMutation({
    mutationFn: () =>
      AnsibleService.triggerAnsibleScan({ projectId: project.id }),
    onSuccess: () => {
      toast.success("Scan queued")
      invalidate()
    },
    onError: (error: Error) => toast.error(apiErrorDetail(error)),
  })

  const toggle = useMutation({
    mutationFn: (enabled: boolean) =>
      AnsibleService.toggleAnsibleProject({ projectId: project.id, enabled }),
    onSuccess: invalidate,
    onError: (error: Error) => toast.error(apiErrorDetail(error)),
  })

  const remove = useMutation({
    mutationFn: () =>
      AnsibleService.deleteAnsibleProject({ projectId: project.id }),
    onSuccess: () => {
      toast.success("Ansible project removed")
      invalidate()
    },
    onError: (error: Error) => toast.error(apiErrorDetail(error)),
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

  const openFindings = (findings ?? []).length

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-4">
        <button
          type="button"
          className="flex min-w-0 items-center gap-2 text-left"
          onClick={onToggleOpen}
        >
          {isOpen ? (
            <ChevronDown className="size-4 shrink-0" />
          ) : (
            <ChevronRight className="size-4 shrink-0" />
          )}
          <CardTitle className="truncate">{project.root_path || "/"}</CardTitle>
          {project.latest_grade && <GradeBadge grade={project.latest_grade} />}
        </button>

        <div className="flex items-center gap-2">
          {project.last_scanned_at && (
            <span className="text-xs text-muted-foreground">
              scanned {formatDateTime(project.last_scanned_at)}
            </span>
          )}
          <Switch
            checked={project.enabled}
            onCheckedChange={(enabled) => toggle.mutate(enabled)}
            aria-label="Enable scanning for this project"
          />
          <Button
            size="sm"
            variant="outline"
            disabled={!project.enabled || scan.isPending}
            onClick={() => scan.mutate()}
          >
            {scan.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Play className="size-4" />
            )}
            Scan
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={remove.isPending}
            onClick={() => remove.mutate()}
            aria-label="Remove this project"
          >
            <Trash2 className="size-4" />
          </Button>
        </div>
      </CardHeader>

      {isOpen && (
        <CardContent className="flex flex-col gap-4">
          {openFindings > 0 && (
            <div className="flex flex-col gap-1">
              {(findings ?? []).map((finding) => (
                <AnsibleFindingRow key={finding.id} finding={finding} />
              ))}
            </div>
          )}

          {files?.map((file) => (
            <FileViewer
              key={file.path}
              path={file.path}
              rawContent={file.raw_content}
              // Every kind this engine reads is YAML — playbooks, task files,
              // variables and galaxy requirements alike — so the classifier's
              // `kind` labels the file rather than picking a grammar.
              grammar="yaml"
              annotations={(findingsByFile.get(file.path) ?? []).map((f) => ({
                id: f.id,
                severity: f.severity,
                rule_slug: f.rule_slug,
                message: f.message,
                line_start: f.line_start,
              }))}
            />
          ))}

          {files?.length === 0 && (
            <p className="py-4 text-center text-sm text-muted-foreground">
              No Ansible files found under this path.
            </p>
          )}
        </CardContent>
      )}
    </Card>
  )
}
