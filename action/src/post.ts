import * as os from "node:os"
import * as path from "node:path"
import * as core from "@actions/core"
import { ingestTelemetry } from "./api"
import { killDaemon, loadState } from "./state"
import { getMetricsSample, getRunnerSpecs } from "./telemetry"

const STATE_FILE = path.join(
  process.env.RUNNER_TEMP ?? os.tmpdir(),
  "greensecops-state.json",
)

async function run(): Promise<void> {
  const state = loadState(STATE_FILE)
  if (!state) {
    // pre step did not run or failed — nothing to finalize
    return
  }

  killDaemon(state.daemonPid)

  const finalMetrics = getMetricsSample()
  const durationMs = Date.now() - new Date(state.startedAt).getTime()

  const ok = await ingestTelemetry(state.greensecopsUrl, state.oidcToken, {
    workflow_run_id: state.workflowRunId,
    repository: state.repository,
    branch: (process.env.GITHUB_REF ?? "").replace("refs/heads/", ""),
    commit_sha: process.env.GITHUB_SHA ?? "",
    workflow_name: process.env.GITHUB_WORKFLOW ?? "",
    runner_specs: getRunnerSpecs(),
    metrics: {
      ...finalMetrics,
      duration_ms: durationMs,
    } as typeof finalMetrics & {
      duration_ms: number
    },
    phase: "completed",
  })

  if (ok) {
    core.info(
      `GreenSecOps: telemetry completed (${Math.round(durationMs / 1000)}s)`,
    )
  } else {
    core.warning(
      "GreenSecOps: final telemetry send failed — workflow result unaffected",
    )
  }
}

run().catch((err: unknown) => {
  core.warning(`GreenSecOps post step error: ${String(err)}`)
})
