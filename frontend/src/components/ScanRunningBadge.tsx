import { Loader2 } from "lucide-react"
import type { ScanStatus } from "@/client"
import { StatusPill } from "@/components/StatusPill"
import { isScanInFlight } from "@/lib/scan-polling"
import { scanStatusColor, scanStatusLabel } from "@/lib/status-colors"

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
  if (!isScanInFlight(status)) return null
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
