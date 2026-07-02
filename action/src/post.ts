import * as core from "@actions/core"
import { ingestTelemetry } from "./api"
import { getGitHubContext, killDaemon, loadState, STATE_FILE } from "./state"
import { getMetricsSample } from "./telemetry"

async function run(): Promise<void> {
  const state = loadState(STATE_FILE)
  if (!state) {
    // pre step did not run or failed — nothing to finalize
    return
  }

  killDaemon(state.daemonPid)

  const finalMetrics = getMetricsSample()
  const durationMs = Date.now() - new Date(state.startedAt).getTime()
  const ctx = getGitHubContext()

  const ok = await ingestTelemetry(state.greensecopsUrl, state.oidcToken, {
    workflow_run_id: state.workflowRunId,
    repository: state.repository,
    branch: ctx.branch,
    commit_sha: ctx.commitSha,
    workflow_name: ctx.workflowName,
    runner_specs: state.runnerSpecs,
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
