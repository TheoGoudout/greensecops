import { spawn } from "node:child_process"
import { writeFileSync } from "node:fs"
import * as os from "node:os"
import * as path from "node:path"
import * as core from "@actions/core"
import { ingestTelemetry } from "./api"
import { getMetricsSample, getRunnerSpecs } from "./telemetry"
import type { ActionState } from "./types"

const STATE_FILE = path.join(
  process.env.RUNNER_TEMP ?? os.tmpdir(),
  "greensecops-state.json",
)

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

  const workflowRunId = parseInt(process.env.GITHUB_RUN_ID ?? "0", 10)
  const repository = process.env.GITHUB_REPOSITORY ?? ""
  const branch = (process.env.GITHUB_REF ?? "").replace("refs/heads/", "")
  const commitSha = process.env.GITHUB_SHA ?? ""
  const workflowName = process.env.GITHUB_WORKFLOW ?? ""

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
    workflowRunId,
    repository,
    startedAt: new Date().toISOString(),
  }

  try {
    writeFileSync(STATE_FILE, JSON.stringify(state), "utf8")
  } catch (err) {
    core.warning(`GreenSecOps: could not write state file: ${String(err)}`)
  }

  const ok = await ingestTelemetry(greensecopsUrl, oidcToken, {
    workflow_run_id: workflowRunId,
    repository,
    branch,
    commit_sha: commitSha,
    workflow_name: workflowName,
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
