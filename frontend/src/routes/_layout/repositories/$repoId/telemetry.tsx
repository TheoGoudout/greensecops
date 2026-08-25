import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import {
  Activity,
  ChevronDown,
  ChevronRight,
  Cpu,
  HardDrive,
  MemoryStick,
  Network,
  Play,
  Puzzle,
} from "lucide-react"
import { useMemo, useState } from "react"
import { toast } from "sonner"
import {
  RepositoriesService,
  type TelemetryRunPublic,
  TelemetryService,
} from "@/client"
import { RuntimeFindingRow } from "@/components/RuntimeFindingRow"
import { StatusPill } from "@/components/StatusPill"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useRepository } from "@/hooks/useRepository"
import { apiErrorDetail } from "@/lib/api-error"
import { dynamicStatusColor } from "@/lib/status-colors"
import { PAGE_SIZE } from "@/lib/workflow-utils"

export const Route = createFileRoute("/_layout/repositories/$repoId/telemetry")(
  {
    component: TelemetryPage,
    head: () => ({
      meta: [{ title: "Telemetry analysis - GreenSecOps" }],
    }),
  },
)

function fmtNumber(value: number | null | undefined, digits = 1): string {
  if (value == null) return "—"
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  })
}

function fmtBytes(value: number | null | undefined): string {
  if (value == null) return "—"
  const units = ["B", "KB", "MB", "GB"]
  let v = value
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${fmtNumber(v)} ${units[i]}`
}

function StatCard({
  icon: Icon,
  title,
  value,
  hint,
  loading,
}: {
  icon: typeof Cpu
  title: string
  value: string
  hint?: string
  loading: boolean
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>
        {loading ? (
          <Skeleton className="h-8 w-20" />
        ) : (
          <>
            <p className="text-2xl font-bold tabular-nums">{value}</p>
            {hint && (
              <p className="text-xs text-muted-foreground mt-0.5">{hint}</p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}

function RunRow({ run }: { run: TelemetryRunPublic }) {
  const [expanded, setExpanded] = useState(false)
  const cpu = run.metrics?.cpu_percent as number | undefined
  const ram = run.metrics?.ram_percent as number | undefined
  const vcpus = run.runner_specs?.vcpus as number | undefined
  const hasEnrichments = (run.enrichments?.length ?? 0) > 0

  return (
    <>
      <button
        type="button"
        onClick={() => hasEnrichments && setExpanded((e) => !e)}
        className={`grid grid-cols-[1.5rem_1fr_6rem_6rem_5rem_6rem] min-w-[38rem] items-center px-6 py-3 gap-4 w-full text-left ${
          hasEnrichments ? "hover:bg-muted/40 cursor-pointer" : "cursor-default"
        } transition-colors`}
      >
        <span className="text-muted-foreground">
          {hasEnrichments ? (
            expanded ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )
          ) : null}
        </span>
        <span className="text-xs font-mono truncate">
          #{run.workflow_run_id}
        </span>
        <span className="text-xs tabular-nums text-right">
          {cpu != null ? `${fmtNumber(cpu)}%` : "—"}
        </span>
        <span className="text-xs tabular-nums text-right">
          {ram != null ? `${fmtNumber(ram)}%` : "—"}
        </span>
        <span className="text-xs tabular-nums text-right">
          {vcpus != null ? vcpus : "—"}
        </span>
        <div className="flex justify-end">
          {run.dynamic_status ? (
            <StatusPill
              colorClass={dynamicStatusColor(run.dynamic_status)}
              className="capitalize"
            >
              {run.dynamic_status}
            </StatusPill>
          ) : (
            <span className="text-xs text-muted-foreground">{run.phase}</span>
          )}
        </div>
      </button>
      {expanded && hasEnrichments && (
        <div className="bg-muted/20 divide-y border-t">
          {run.enrichments?.map((finding) => (
            <RuntimeFindingRow key={finding.id} finding={finding} />
          ))}
        </div>
      )}
    </>
  )
}

function TelemetryPage() {
  const { repoId } = Route.useParams()
  const queryClient = useQueryClient()
  const [page, setPage] = useState(0)

  const { isAccessible } = useRepository(repoId)

  const { data: summary, isLoading } = useQuery({
    queryKey: ["telemetry", "summary", repoId],
    queryFn: () => TelemetryService.getTelemetrySummary({ repoId, limit: 200 }),
  })

  const analyzeMutation = useMutation({
    mutationFn: () => TelemetryService.analyzeTelemetry({ repoId }),
    onSuccess: (data) => {
      const runs = (data as { runs?: number })?.runs ?? 0
      toast.success(
        runs > 0
          ? `Telemetry analysis queued for ${runs} run${runs !== 1 ? "s" : ""}`
          : "No completed telemetry runs to analyze yet",
      )
      queryClient.invalidateQueries({
        queryKey: ["telemetry", "summary", repoId],
      })
      queryClient.invalidateQueries({
        queryKey: ["telemetry", "findings", repoId],
      })
    },
    onError: (error) =>
      toast.error("Failed to queue telemetry analysis", {
        description: apiErrorDetail(error),
      }),
  })

  // "Integrate action" opens a PR adding the GreenSecOps action to the repo.
  // It lives on this tab because telemetry only flows once the action runs.
  const integrateActionMutation = useMutation({
    mutationFn: () => RepositoriesService.integrateAction({ repoId }),
    onSuccess: (data) => {
      toast.success("PR opened", {
        description: data.pr_url,
        action: data.pr_url
          ? {
              label: "Open",
              onClick: () => window.open(data.pr_url, "_blank"),
            }
          : undefined,
      })
    },
    onError: (error) =>
      toast.error("Failed to integrate action", {
        description: apiErrorDetail(error),
      }),
  })

  const avg = summary?.average
  const runs = useMemo(() => summary?.runs ?? [], [summary])
  const findings = useMemo(
    () => runs.flatMap((r) => r.enrichments ?? []),
    [runs],
  )
  const pagedRuns = useMemo(
    () => runs.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE),
    [runs, page],
  )

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <p className="text-sm text-muted-foreground">
          Runtime metrics collected while your workflows run
          {avg
            ? ` · ${avg.run_count} run${avg.run_count !== 1 ? "s" : ""}`
            : ""}
          .
        </p>
        <div className="flex items-center gap-2 flex-wrap">
          <Button
            variant="outline"
            size="sm"
            className="gap-2"
            onClick={() => integrateActionMutation.mutate()}
            disabled={
              !isAccessible ||
              integrateActionMutation.isPending ||
              integrateActionMutation.isSuccess
            }
          >
            <Puzzle className="h-4 w-4" />
            {integrateActionMutation.isPending
              ? "Opening PR…"
              : integrateActionMutation.isSuccess
                ? "PR opened"
                : "Integrate action"}
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="gap-2"
            onClick={() => analyzeMutation.mutate()}
            disabled={!isAccessible || analyzeMutation.isPending}
          >
            <Play className="h-4 w-4" />
            {analyzeMutation.isPending ? "Queuing…" : "Run telemetry analysis"}
          </Button>
        </div>
      </div>

      {/* Averages */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard
          icon={Cpu}
          title="Avg CPU"
          value={
            avg?.avg_cpu_percent != null
              ? `${fmtNumber(avg.avg_cpu_percent)}%`
              : "—"
          }
          hint={
            avg?.avg_vcpus != null
              ? `${fmtNumber(avg.avg_vcpus)} vCPUs`
              : undefined
          }
          loading={isLoading}
        />
        <StatCard
          icon={MemoryStick}
          title="Avg RAM"
          value={
            avg?.avg_ram_percent != null
              ? `${fmtNumber(avg.avg_ram_percent)}%`
              : "—"
          }
          hint={
            avg?.avg_ram_used_mb != null
              ? `${fmtNumber(avg.avg_ram_used_mb)} MB used`
              : undefined
          }
          loading={isLoading}
        />
        <StatCard
          icon={HardDrive}
          title="Avg Disk"
          value={
            avg?.avg_disk_used_gb != null
              ? `${fmtNumber(avg.avg_disk_used_gb)} GB`
              : "—"
          }
          loading={isLoading}
        />
        <StatCard
          icon={Network}
          title="Avg Network"
          value={
            avg?.avg_net_bytes_sent != null || avg?.avg_net_bytes_recv != null
              ? `↑${fmtBytes(avg?.avg_net_bytes_sent)} ↓${fmtBytes(avg?.avg_net_bytes_recv)}`
              : "—"
          }
          hint={
            avg?.sample_count != null
              ? `${avg.sample_count} samples`
              : undefined
          }
          loading={isLoading}
        />
      </div>

      {/* Runtime findings */}
      {!isLoading && findings.length > 0 && (
        <Card>
          <CardHeader className="pb-2 pt-4">
            <CardTitle className="text-sm flex items-center gap-2">
              <Activity className="h-4 w-4 text-amber-600 dark:text-amber-400" />
              Runtime findings
              <span className="text-muted-foreground font-normal text-xs">
                ({findings.length})
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <div className="divide-y">
              {findings.map((finding) => (
                <RuntimeFindingRow key={finding.id} finding={finding} />
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* By run */}
      <Card>
        <CardHeader className="pb-2 pt-4">
          <CardTitle className="text-sm">Telemetry by run</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="flex flex-col gap-2 p-6">
              {[...Array(4)].map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : runs.length === 0 ? (
            <p className="text-sm text-muted-foreground p-6 text-center">
              No telemetry collected yet. Telemetry is gathered automatically
              while your workflows run once the GreenSecOps action is
              integrated.
            </p>
          ) : (
            <>
              <div className="overflow-x-auto">
                <div className="grid grid-cols-[1.5rem_1fr_6rem_6rem_5rem_6rem] min-w-[38rem] items-center px-6 py-2 border-b text-xs font-medium text-muted-foreground uppercase tracking-wide gap-4">
                  <span />
                  <span>Run</span>
                  <span className="text-right">CPU</span>
                  <span className="text-right">RAM</span>
                  <span className="text-right">vCPUs</span>
                  <span className="text-right">Status</span>
                </div>
                <div className="divide-y">
                  {pagedRuns.map((run) => (
                    <RunRow key={run.id} run={run} />
                  ))}
                </div>
              </div>
              {runs.length > PAGE_SIZE && (
                <div className="flex items-center justify-between px-6 py-3 border-t">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={page === 0}
                    onClick={() => setPage((p) => p - 1)}
                  >
                    Previous
                  </Button>
                  <span className="text-xs text-muted-foreground">
                    Page {page + 1} of {Math.ceil(runs.length / PAGE_SIZE)}
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={(page + 1) * PAGE_SIZE >= runs.length}
                    onClick={() => setPage((p) => p + 1)}
                  >
                    Next
                  </Button>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
