import type { ScanStatus } from "@/client"

/**
 * Scan states that have not finished yet.
 *
 * `latest_grade` and `latest_score` only ever reflect a *completed* scan, so
 * this is the only thing that distinguishes "a scan is happening" from "this
 * target is idle".
 */
const IN_FLIGHT: ReadonlySet<ScanStatus> = new Set<ScanStatus>([
  "queued",
  "running",
])

/**
 * A type guard, so a caller that has ruled out "not running" also has a
 * non-null status to render — which is what `ScanRunningBadge` needs after it
 * returns early.
 */
export function isScanInFlight(
  status: ScanStatus | null | undefined,
): status is ScanStatus {
  return status != null && IN_FLIGHT.has(status)
}

/**
 * How often to re-ask the server while a scan is running.
 *
 * Five seconds is short enough that a finished scan appears without the user
 * wondering whether anything is happening, and long enough that a page of
 * targets is not a load generator. It only applies while something is actually
 * in flight — see `pollWhileScanning`.
 */
export const SCAN_POLL_MS = 5_000

/**
 * A TanStack `refetchInterval` that runs only while a scan is unfinished.
 *
 * The file engines publish no live events — `SSESignal` covers the CI-workflow
 * engine only — and the sole refresh a Terraform, Docker or Ansible page ever
 * did was the one invalidate fired when the *trigger* request returned. That
 * happens when the scan is **queued**, so the card showed "queued" and then sat
 * there: everything the worker did afterwards reached the browser only on a
 * manual reload. Queue several scans and each one looked stuck in turn.
 *
 * Polling rather than extending SSE to four more engines: this is contained in
 * the page that needs it, and it stops the moment nothing is running, so an
 * idle dashboard costs nothing.
 */
export function pollWhileScanning(
  statuses: readonly (ScanStatus | null | undefined)[],
): number | false {
  return statuses.some(isScanInFlight) ? SCAN_POLL_MS : false
}
