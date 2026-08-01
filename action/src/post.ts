import * as core from "@actions/core"
import { ingestDockerBuild, ingestTelemetry } from "./api"
import {
  accumulate,
  drainEvents,
  loadUsage,
  sampleContainers,
  saveUsage,
} from "./containers"
import { collectBuild, listImageIds } from "./docker"
import {
  CONTAINERS_FILE,
  getGitHubContext,
  killDaemon,
  loadState,
  STATE_FILE,
} from "./state"
import { reportIngest, runStep } from "./step"
import { getMetricsSample } from "./telemetry"
import type { ActionState } from "./types"

/**
 * One last container sweep, after the daemon has been stopped.
 *
 * The daemon's final tick can be up to `sample_interval` seconds before the job
 * ends, and a container that died inside that window would otherwise go
 * unrecorded. Re-draining events from the start of the job closes the gap;
 * replaying events already seen is harmless because the accumulator only ever
 * moves peaks upward and sets terminal flags idempotently.
 */
function finalContainerSweep(state: ActionState): void {
  try {
    const usage = accumulate(
      loadUsage(CONTAINERS_FILE),
      sampleContainers(),
      drainEvents(
        new Date(state.startedAt).getTime() / 1000,
        Date.now() / 1000,
      ),
    )
    saveUsage(CONTAINERS_FILE, usage)
  } catch {
    // best-effort, as everywhere else in the collector
  }
}

/**
 * Report every image this job built.
 *
 * Diffed against the pre-step snapshot so images the runner already shipped are
 * never attributed to this build. One post per image, because the backend keys
 * build telemetry per image rather than per run.
 */
async function reportDockerBuilds(state: ActionState): Promise<void> {
  const before = new Set(state.preImageIds ?? [])
  const built = listImageIds().filter((id) => !before.has(id))
  if (built.length === 0) return

  const usage = loadUsage(CONTAINERS_FILE)
  const metadataPath = core.getInput("docker_build_metadata") || undefined
  const dockerfilePath = core.getInput("dockerfile_path") || undefined

  let posted = 0
  for (const imageId of built) {
    const payload = collectBuild(imageId, state.workflowRunId, {
      metadataPath,
      dockerfilePath,
      usage,
    })
    if (!payload) continue
    if (
      await ingestDockerBuild(state.greensecopsUrl, state.oidcToken, payload)
    ) {
      posted += 1
    }
  }

  if (posted > 0) {
    core.info(
      `GreenSecOps: reported ${posted} image build${posted === 1 ? "" : "s"}`,
    )
  }
}

async function run(): Promise<void> {
  const state = loadState(STATE_FILE)
  if (!state) {
    // pre step did not run or failed — nothing to finalize
    return
  }

  killDaemon(state.daemonPid)
  finalContainerSweep(state)

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

  // Sent after the run telemetry so a Docker-side failure can never cost the
  // caller the metrics every workflow depends on.
  try {
    await reportDockerBuilds(state)
  } catch {
    core.info("GreenSecOps: Docker build telemetry skipped")
  }
}

runStep("post", run)
