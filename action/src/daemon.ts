import { refreshOidcToken, sendSample } from "./api"
import {
  accumulate,
  drainEvents,
  loadUsage,
  sampleContainers,
  saveUsage,
} from "./containers"
import { getTopProcesses } from "./native"
import { CONTAINERS_FILE, loadState, STATE_FILE } from "./state"
import { getMetricsSample } from "./telemetry"
import type { SamplePayload } from "./types"

const SAMPLE_INTERVAL_MS =
  parseInt(process.env.INPUT_SAMPLE_INTERVAL ?? "30", 10) * 1000

// refresh every 4 min to stay ahead of typical 5-min OIDC token TTL
const TOKEN_REFRESH_INTERVAL_MS = 4 * 60 * 1000

async function run(): Promise<void> {
  const state = loadState(STATE_FILE)
  if (!state) {
    // pre step did not complete — exit silently, do not disrupt workflow
    process.exit(0)
  }

  let { oidcToken } = state
  const { greensecopsUrl, workflowRunId } = state
  let lastTokenRefresh = Date.now()
  // Events are drained in closed windows, so the first one has to start where
  // the job did — a container that died before the first tick still counts.
  let lastEventSweep = new Date(state.startedAt).getTime() / 1000

  async function maybeRefreshToken(): Promise<void> {
    if (Date.now() - lastTokenRefresh < TOKEN_REFRESH_INTERVAL_MS) return
    try {
      const fresh = await refreshOidcToken()
      if (fresh) {
        oidcToken = fresh
        lastTokenRefresh = Date.now()
      }
    } catch {
      // ignore refresh failure — keep using current token
    }
  }

  /**
   * Fold this tick's container readings into the on-disk accumulator.
   *
   * Written every tick rather than once at the end because the daemon is
   * SIGTERM'd by the post step — anything held only in memory would be lost
   * exactly when it is about to be reported.
   */
  function sweepContainers(): void {
    try {
      const now = Date.now() / 1000
      const usage = accumulate(
        loadUsage(CONTAINERS_FILE),
        sampleContainers(),
        drainEvents(lastEventSweep, now),
      )
      lastEventSweep = now
      saveUsage(CONTAINERS_FILE, usage)
    } catch {
      // container telemetry is strictly best-effort
    }
  }

  async function tick(): Promise<void> {
    try {
      await maybeRefreshToken()
      sweepContainers()
      const metrics = getMetricsSample()
      const topProcesses = getTopProcesses()
      await sendSample(greensecopsUrl, oidcToken, {
        workflow_run_id: workflowRunId,
        cpu_percent: metrics.cpu_load_percent,
        ram_used_mb: metrics.ram_used_mb,
        disk_used_gb: metrics.disk_used_gb,
        net_bytes_sent: metrics.net_bytes_sent,
        net_bytes_recv: metrics.net_bytes_recv,
        ...(topProcesses
          ? {
              top_processes:
                topProcesses as unknown as SamplePayload["top_processes"],
            }
          : {}),
      })
    } catch {
      // swallow all errors — daemon must never crash the runner
    }
  }

  process.on("SIGTERM", () => process.exit(0))
  process.on("SIGINT", () => process.exit(0))

  await tick()
  setInterval(() => {
    void tick()
  }, SAMPLE_INTERVAL_MS)
}

void run()
