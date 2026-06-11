import { readFileSync } from "node:fs"
import * as os from "node:os"
import * as path from "node:path"
import { refreshOidcToken, sendSample } from "./api"
import { getMetricsSample } from "./telemetry"
import type { ActionState } from "./types"

const STATE_FILE = path.join(
  process.env.RUNNER_TEMP ?? os.tmpdir(),
  "greensecops-state.json",
)
const SAMPLE_INTERVAL_MS =
  parseInt(process.env.INPUT_SAMPLE_INTERVAL ?? "30", 10) * 1000

// refresh every 4 min to stay ahead of typical 5-min OIDC token TTL
const TOKEN_REFRESH_INTERVAL_MS = 4 * 60 * 1000

function loadState(): ActionState | null {
  try {
    return JSON.parse(readFileSync(STATE_FILE, "utf8")) as ActionState
  } catch {
    return null
  }
}

async function run(): Promise<void> {
  const state = loadState()
  if (!state) {
    // pre step did not complete — exit silently, do not disrupt workflow
    process.exit(0)
  }

  let { oidcToken } = state
  const { greensecopsUrl, workflowRunId } = state
  let lastTokenRefresh = Date.now()

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

  async function tick(): Promise<void> {
    try {
      await maybeRefreshToken()
      const metrics = getMetricsSample()
      await sendSample(greensecopsUrl, oidcToken, {
        workflow_run_id: workflowRunId,
        cpu_percent: metrics.cpu_load_percent,
        ram_used_mb: metrics.ram_used_mb,
        disk_used_gb: metrics.disk_used_gb,
        net_bytes_sent: metrics.net_bytes_sent,
        net_bytes_recv: metrics.net_bytes_recv,
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
