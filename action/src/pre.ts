import { spawn } from "node:child_process"
import { writeFileSync } from "node:fs"
import * as path from "node:path"
import * as core from "@actions/core"
import { ingestTelemetry } from "./api"
import { getGitHubContext, STATE_FILE } from "./state"
import { getMetricsSample, getRunnerSpecs } from "./telemetry"
import type { ActionState } from "./types"

async function run(): Promise<void> {
  const greensecopsUrl = core
    .getInput("greensecops_url", { required: true })
    .replace(/\/$/, "")

  let oidcToken: string
  try {
    oidcToken = await core.getIDToken("greensecops")
  } catch (err) {
    core.warning(
      "GreenSecOps: could not obtain OIDC token. " +
        "Ensure your workflow has `permissions: id-token: write`. " +
        `Error: ${String(err)}`,
    )
    return
  }

  const ctx = getGitHubContext()
  const runnerSpecs = getRunnerSpecs()
  const initialMetrics = getMetricsSample()

  // spawn background daemon — detached so it outlives this process
  const actionRoot =
    process.env.GITHUB_ACTION_PATH ?? path.join(__dirname, "..", "..")
  const daemonPath = path.join(actionRoot, "dist", "daemon", "index.js")
  const daemon = spawn(process.execPath, [daemonPath], {
    detached: true,
    stdio: "ignore",
    env: { ...process.env },
  })
  daemon.unref()

  const state: ActionState = {
    daemonPid: daemon.pid ?? 0,
    greensecopsUrl,
    oidcToken,
    workflowRunId: ctx.workflowRunId,
    repository: ctx.repository,
    runnerSpecs,
    startedAt: new Date().toISOString(),
  }

  try {
    writeFileSync(STATE_FILE, JSON.stringify(state), "utf8")
  } catch (err) {
    core.warning(`GreenSecOps: could not write state file: ${String(err)}`)
  }

  const ok = await ingestTelemetry(greensecopsUrl, oidcToken, {
    workflow_run_id: ctx.workflowRunId,
    repository: ctx.repository,
    branch: ctx.branch,
    commit_sha: ctx.commitSha,
    workflow_name: ctx.workflowName,
    runner_specs: runnerSpecs,
    metrics: initialMetrics,
    phase: "started",
  })

  if (ok) {
    core.info("GreenSecOps: telemetry collection started")
  } else {
    core.warning(
      "GreenSecOps: initial telemetry send failed — workflow continues normally",
    )
  }
}

run().catch((err: unknown) => {
  core.warning(`GreenSecOps pre step error: ${String(err)}`)
})
