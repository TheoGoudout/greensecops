import { ingestTelemetry } from "./api"
import { getGitHubContext, killDaemon, loadState, STATE_FILE } from "./state"
import { reportIngest, runStep } from "./step"
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
    branch: ctx.branch,
    commit_sha: ctx.commitSha,
    workflow_name: ctx.workflowName,
    runner_specs: state.runnerSpecs,
    metrics: { ...finalMetrics, duration_ms: durationMs },
    phase: "completed",
  })

  reportIngest(
    ok,
    `GreenSecOps: telemetry completed (${Math.round(durationMs / 1000)}s)`,
    "GreenSecOps: final telemetry send failed — workflow result unaffected",
  )
}

runStep("post", run)
