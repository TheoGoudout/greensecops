import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import type { DockerTargetPublic } from "@/client"
import { DockerService } from "@/client"
import { GradeBadge } from "@/components/GradeBadge"
import { StatusPill } from "@/components/StatusPill"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { scanStatusColor, scanStatusLabel } from "@/lib/status-colors"

export const Route = createFileRoute("/_layout/docker/$repoId/scans")({
  component: DockerScansTab,
  head: () => ({
    meta: [{ title: "Docker scan history - GreenSecOps" }],
  }),
})

function DockerScansTab() {
  const { repoId } = Route.useParams()

  const { data: targets, isLoading } = useQuery({
    queryKey: ["docker-targets", "repo", repoId],
    queryFn: () => DockerService.listTargets({ repoId }),
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
          No Docker targets yet, so there is nothing to show a history for.
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      {targets.map((target) => (
        <TargetScanHistory key={target.id} target={target} />
      ))}
    </div>
  )
}

function TargetScanHistory({ target }: { target: DockerTargetPublic }) {
  const { data: scans, isLoading } = useQuery({
    queryKey: ["docker-scans", target.id],
    queryFn: () => DockerService.listScans({ targetId: target.id }),
  })

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="font-mono text-sm break-all">
          {target.root_path === "" ? "/ (repository root)" : target.root_path}
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        {isLoading ? (
          <div className="flex flex-col gap-2 px-6 pb-6">
            {[...Array(3)].map((_, i) => (
              <Skeleton key={i} className="h-8 w-full" />
            ))}
          </div>
        ) : !scans?.length ? (
          <p className="text-sm text-muted-foreground px-6 pb-6">
            Never scanned. Trigger one from the Analysis tab.
          </p>
        ) : (
          <div className="divide-y">
            {scans.map((scan) => (
              <div
                key={scan.id}
                className="flex items-center gap-3 flex-wrap px-6 py-3 text-xs text-muted-foreground"
              >
                <StatusPill colorClass={scanStatusColor(scan.status)}>
                  {scanStatusLabel(scan.status)}
                </StatusPill>
                <span className="capitalize">{scan.triggered_by}</span>
                <GradeBadge grade={scan.grade ?? null} />
                {/* The score is a mean of per-file scores — showing the
                    denominator is what makes the grade interpretable. */}
                {scan.file_count != null && (
                  <span>
                    {scan.file_count} file{scan.file_count !== 1 ? "s" : ""}
                  </span>
                )}
                {scan.branch && (
                  <span className="font-mono truncate">{scan.branch}</span>
                )}
                <span className="tabular-nums whitespace-nowrap ml-auto">
                  {scan.created_at
                    ? new Date(scan.created_at).toLocaleString()
                    : ""}
                </span>
                {scan.error_message && (
                  <p className="w-full text-destructive break-words">
                    {scan.error_message}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
