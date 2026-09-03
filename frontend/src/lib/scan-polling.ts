import type { ScanStatus, TargetActivity } from "@/client"

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

/**
 * How often to re-ask while nothing appears to be running.
 *
 * Thirty seconds, because "nothing appears to be running" is the state this
 * page can be wrong about. `pollWhileScanning` starts polling only once the
 * data it already holds shows a scan — so work started anywhere else (the
 * GitHub Action on a push, a webhook, a teammate on the same repository) is
 * invisible until something else happens to refetch, and every action stays
 * live over it. A slow baseline poll is what closes that: the buttons grey
 * within half a minute rather than never.
 */
export const IDLE_POLL_MS = 30_000

/**
 * A `refetchInterval` that never stops, but slows down when nothing is in
 * flight.
 *
 * For the target and repository *lists* — the cheap reads that carry
 * `activity` and gate the buttons drawn beside them. The heavier per-target
 * reads keep `pollWhileScanning`: they are a request each and there is no
 * point re-asking a settled one on a timer.
 *
 * Takes the rows' `activity` rather than their scan status, because that is
 * the field the buttons are gated on and it covers fix work too — a target
 * whose fixes a worker is writing is exactly as unavailable as one being
 * scanned, and its scan status says `completed`.
 */
export function pollForActivity(
  activities: readonly (TargetActivity | null | undefined)[],
): number {
  return activities.some((a) => a && a !== "idle") ? SCAN_POLL_MS : IDLE_POLL_MS
}
