import { spawn } from "node:child_process"
import { writeFileSync } from "node:fs"
import * as path from "node:path"
import * as core from "@actions/core"
import { ingestTelemetry } from "./api"
import { listImageIds } from "./docker"
import { getGitHubContext, STATE_FILE } from "./state"
import { reportIngest, runStep } from "./step"
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
    // Baseline for the post step's diff. Empty on a runner without Docker,
    // which simply means every image found later counts as newly built — the
    // same answer, since there were none to begin with.
    preImageIds: listImageIds(),
  }

  try {
    writeFileSync(STATE_FILE, JSON.stringify(state), "utf8")
  } catch (err) {
    core.warning(`GreenSecOps: could not write state file: ${String(err)}`)
  }

  const ok = await ingestTelemetry(greensecopsUrl, oidcToken, {
    workflow_run_id: ctx.workflowRunId,
    branch: ctx.branch,
    commit_sha: ctx.commitSha,
    workflow_name: ctx.workflowName,
    runner_specs: runnerSpecs,
    metrics: initialMetrics,
    phase: "started",
  })

  reportIngest(
    ok,
    "GreenSecOps: telemetry collection started",
    "GreenSecOps: initial telemetry send failed — workflow continues normally",
  )
}

runStep("pre", run)
