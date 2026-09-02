import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { ChevronDown, ChevronRight } from "lucide-react"
import { useMemo, useState } from "react"
import { toast } from "sonner"
import type { DockerBuildTelemetryPublic, DockerTargetPublic } from "@/client"
import { DockerService } from "@/client"
import { DockerRuntimeFindingRow } from "@/components/DockerRuntimeFindingRow"
import { EngineActionButton } from "@/components/EngineActionBar"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useRepository } from "@/hooks/useRepository"
import { apiErrorDetail } from "@/lib/api-error"
import { engineActions } from "@/lib/engine-actions"
import { severityRank } from "@/lib/severity"

export const Route = createFileRoute("/_layout/docker/$repoId/runtime")({
  component: DockerRuntimeTab,
  head: () => ({
    meta: [{ title: "Docker runtime - GreenSecOps" }],
  }),
})

function DockerRuntimeTab() {
  const { repoId } = Route.useParams()
  const [openTargets, setOpenTargets] = useState<Set<string>>(new Set())
  const { isAccessible } = useRepository(repoId)

  const { data: targets, isLoading } = useQuery({
    queryKey: ["docker-targets", "repo", repoId],
    queryFn: () => DockerService.listTargets({ repoId }),
  })

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
        <RuntimeTargetCard
          key={target.id}
          target={target}
          isOpen={openTargets.has(target.id)}
          onToggleOpen={() => toggleOpen(target.id)}
          isAccessible={isAccessible}
        />
      ))}
    </div>
  )
}

function RuntimeTargetCard({
  target,
  isOpen,
  onToggleOpen,
  isAccessible,
}: {
  target: DockerTargetPublic
  isOpen: boolean
  onToggleOpen: () => void
  isAccessible: boolean
}) {
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState<Set<string>>(new Set())

  // Loaded only once expanded, matching the Analysis tab — a repo can hold
  // many targets and each card is a separate query.
  const { data: builds, isLoading } = useQuery({
    queryKey: ["docker-runtime", target.id],
    queryFn: () => DockerService.listRuntimeFindings({ targetId: target.id }),
    enabled: isOpen,
  })

  // A runtime fix is written into the same Dockerfile a static fix would be, so
  // it obeys the same rules and shares the Analysis tab's cache entry rather
  // than asking for the fix list a second time.
  const { data: fixes } = useQuery({
    queryKey: ["docker-fixes", target.id],
    queryFn: () => DockerService.listFixes({ targetId: target.id }),
  })

  const fixMutation = useMutation({
    mutationFn: (enrichmentIds: string[]) =>
      DockerService.generateRuntimeFixes({
        targetId: target.id,
        requestBody: { enrichment_ids: enrichmentIds },
      }),
    onSuccess: (result) => {
      // The route reports 0 when every selected finding came from a build with
      // no dockerfile_path — there is no file to rewrite, and saying "queued"
      // would leave the user waiting for a fix that was never started.
      const queued = (result as { queued?: number })?.queued ?? 0
      if (queued === 0) {
        toast.error("Nothing to fix", {
          description:
            "These builds were reported without a dockerfile_path, so there is no file to rewrite. Set the action's dockerfile_path input.",
        })
        return
      }
      toast.success("Fix generation queued")
      setSelected(new Set())
      queryClient.invalidateQueries({ queryKey: ["docker-fixes", target.id] })
      queryClient.invalidateQueries({ queryKey: ["pull-requests", "repo"] })
    },
    onError: (e) =>
      toast.error("Could not queue fixes", { description: apiErrorDetail(e) }),
  })

  const findingCount = useMemo(
    () => (builds ?? []).reduce((n, b) => n + (b.findings?.length ?? 0), 0),
    [builds],
  )

  // Only findings from a build that names a Dockerfile can drive a fix. The
  // rest still render — the measurement is real — but cannot be selected.
  const fixableIds = useMemo(() => {
    const ids = new Set<string>()
    for (const build of builds ?? []) {
      if (!build.dockerfile_path) continue
      for (const finding of build.findings ?? []) ids.add(finding.id)
    }
    return ids
  }, [builds])

  const toggleFinding = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
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
              {isOpen && builds
                ? `${builds.length} measured build${builds.length !== 1 ? "s" : ""}` +
                  (findingCount > 0
                    ? ` · ${findingCount} finding${findingCount !== 1 ? "s" : ""}`
                    : "")
                : "Measured from CI telemetry"}
            </p>
          </div>
        </div>

        {isOpen && selected.size > 0 && (
          <EngineActionButton
            action={
              engineActions({
                targetLabel: "Docker target",
                scope: "target",
                isAccessible,
                enabled: target.enabled,
                scanStatus: target.latest_scan_status,
                fixStatuses: (fixes ?? []).map((f) => f.status),
                openFindingCount: selected.size,
                count: selected.size,
                pending: { generate: fixMutation.isPending },
              }).generate
            }
            onClick={() => fixMutation.mutate([...selected])}
            compact
          />
        )}
      </CardHeader>

      {isOpen && (
        <CardContent className="flex flex-col gap-4">
          {isLoading && <Skeleton className="h-24 w-full" />}
          {!isLoading && (builds ?? []).length === 0 && (
            <p className="text-sm text-muted-foreground py-6 text-center">
              No measured builds yet. Add the GreenSecOps action to a workflow
              that builds images — it reports image size, layers, cache hits and
              how the containers behaved.
            </p>
          )}
          {(builds ?? []).map((build) => (
            <BuildCard
              key={build.id}
              build={build}
              selected={selected}
              onToggleFinding={toggleFinding}
              fixableIds={fixableIds}
            />
          ))}
        </CardContent>
      )}
    </Card>
  )
}

function BuildCard({
  build,
  selected,
  onToggleFinding,
  fixableIds,
}: {
  build: DockerBuildTelemetryPublic
  selected: Set<string>
  onToggleFinding: (id: string) => void
  fixableIds: Set<string>
}) {
  const findings = useMemo(
    () =>
      [...(build.findings ?? [])].sort(
        (a, b) =>
          severityRank(a.severity ?? "info") -
          severityRank(b.severity ?? "info"),
      ),
    [build.findings],
  )

  return (
    <div className="rounded-lg border">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 px-6 py-3 border-b bg-muted/30">
        <span className="font-mono text-xs break-all">
          {build.dockerfile_path ?? "(no dockerfile_path reported)"}
        </span>
        <span className="text-xs text-muted-foreground">
          run #{build.workflow_run_id}
        </span>
        {build.collected_at && (
          <span className="text-xs text-muted-foreground">
            {new Date(build.collected_at).toLocaleString()}
          </span>
        )}
      </div>

      <dl className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-2 px-6 py-3 text-xs">
        <Metric
          label="Image size"
          value={formatBytes(build.image_size_bytes)}
        />
        <Metric
          label="Build context"
          value={formatBytes(build.context_size_bytes)}
        />
        <Metric
          label="Cache hits"
          value={formatPercent(build.cache_hit_ratio)}
        />
        <Metric label="Layers" value={`${build.layers?.length ?? 0}`} />
      </dl>

      {(build.containers?.length ?? 0) > 0 && (
        <div className="px-6 pb-3">
          <ContainerTable containers={build.containers ?? []} />
        </div>
      )}

      {findings.length > 0 && (
        <div className="border-t divide-y">
          {findings.map((finding) => (
            <DockerRuntimeFindingRow
              key={finding.id}
              finding={finding}
              selected={selected.has(finding.id)}
              onToggle={() => onToggleFinding(finding.id)}
              selectable={fixableIds.has(finding.id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-mono truncate">{value}</dd>
    </div>
  )
}

/**
 * Per-container measurements.
 *
 * A dash rather than a zero for anything unmeasured: the collector reports
 * null when a counter was never read, and rendering that as 0 would claim a
 * container peaked at nothing.
 */
function ContainerTable({
  containers,
}: {
  containers: Array<Record<string, unknown>>
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="text-muted-foreground">
          <tr className="text-left">
            <th className="font-normal py-1 pr-4">Container</th>
            <th className="font-normal py-1 pr-4">Peak RSS</th>
            <th className="font-normal py-1 pr-4">Limit</th>
            <th className="font-normal py-1 pr-4">Throttled</th>
            <th className="font-normal py-1">State</th>
          </tr>
        </thead>
        <tbody className="font-mono">
          {containers.map((container, index) => {
            const name = String(container.name ?? "—")
            return (
              <tr key={`${name}-${index}`} className="border-t">
                <td className="py-1 pr-4 break-all">{name}</td>
                <td className="py-1 pr-4">
                  {formatBytes(asNumber(container.peak_rss_bytes))}
                </td>
                <td className="py-1 pr-4">
                  {container.mem_limit_bytes === 0
                    ? "none"
                    : formatBytes(asNumber(container.mem_limit_bytes))}
                </td>
                <td className="py-1 pr-4">
                  {formatPercentValue(
                    asNumber(container.cpu_throttled_percent),
                  )}
                </td>
                <td className="py-1">
                  {container.oom_killed === true ? (
                    <span className="text-red-600 dark:text-red-400">
                      OOM-killed
                    </span>
                  ) : (
                    (container.health_status as string) || "—"
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

const asNumber = (value: unknown): number | null =>
  typeof value === "number" ? value : null

function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "—"
  // Decimal units, matching how `docker history` and `docker image inspect`
  // report sizes — the same convention the collector normalises to.
  const units = ["B", "kB", "MB", "GB", "TB"]
  let value = bytes
  let unit = 0
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000
    unit += 1
  }
  return `${value < 10 && unit > 0 ? value.toFixed(1) : Math.round(value)} ${units[unit]}`
}

function formatPercent(ratio: number | null | undefined): string {
  if (ratio == null) return "—"
  return `${Math.round(ratio * 100)}%`
}

function formatPercentValue(percent: number | null | undefined): string {
  if (percent == null) return "—"
  return `${percent}%`
}
