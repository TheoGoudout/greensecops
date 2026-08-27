import { Loader2 } from "lucide-react"
import type { ScanStatus } from "@/client"
import { StatusPill } from "@/components/StatusPill"
import { scanStatusColor, scanStatusLabel } from "@/lib/status-colors"

const IN_FLIGHT = new Set<ScanStatus>(["queued", "running"])

/**
 * Badge shown on a target card while its latest scan hasn't finished yet.
 *
 * `latest_grade`/`latest_score` only ever reflect the last *completed* scan,
 * so without this a scan in flight looks identical to an idle target.
 */
export function ScanRunningBadge({
  status,
}: {
  status: ScanStatus | null | undefined
}) {
  if (!status || !IN_FLIGHT.has(status)) return null
  return (
    <StatusPill
      colorClass={scanStatusColor(status)}
      className="inline-flex items-center gap-1 shrink-0"
    >
      <Loader2 className="h-3 w-3 animate-spin" />
      {scanStatusLabel(status)}
    </StatusPill>
  )
}
