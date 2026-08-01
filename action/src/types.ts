export interface RunnerSpecs {
  os: string
  arch: string
  runner_name: string
  platform: string
  node_version: string
  vcpus: number
  ram_total_gb: number
  disk_total_gb?: number
  disk_free_gb?: number
}

export interface TopProcess {
  pid: number
  name: string
  cpu_percent: number
  mem_percent: number
  mem_rss_mb: number
}

export interface MetricsSample {
  collected_at: number
  cpu_load_percent?: number
  ram_used_mb?: number
  ram_percent?: number
  disk_used_gb?: number
  net_bytes_sent?: number
  net_bytes_recv?: number
  // set by the post step only: wall-clock duration of the workflow run
  duration_ms?: number
  // Linux-only, from the proc-sampler binary; absent on other platforms or
  // if the binary is unavailable/fails.
  top_processes?: TopProcess[]
}

import type { TelemetryPhase } from "./client/types.gen"

export type { SamplePayload, TelemetryPhase } from "./client/types.gen"

// Hand-written, strongly-typed counterpart of the generated TelemetryPayload
// (client/types.gen.ts), whose runner_specs/metrics are untyped dicts. The
// backend identifies the repository from the OIDC token claims, so no
// repository field is sent.
export interface IngestPayload {
  workflow_run_id: number
  branch: string
  commit_sha: string
  workflow_name: string
  runner_specs: RunnerSpecs
  metrics: MetricsSample
  phase?: TelemetryPhase
}

export interface DockerLayer {
  index: number
  size_bytes: number
  // Instruction keyword only. `docker history` reports the literal RUN
  // command, which routinely contains build args and inline credentials, so
  // the text is discarded on the runner rather than shipped and redacted.
  instruction: string
}

/**
 * What the daemon accumulated about one container over the life of the job.
 *
 * Kept separate from ContainerStats because it survives the container: peaks
 * and terminal events are folded in while the container is alive, then merged
 * with whatever `docker inspect` can still report in the post step.
 */
export interface ContainerUsage {
  name: string
  id: string
  peak_rss_bytes: number | null
  peak_pids: number | null
  cpu_throttled_percent: number | null
  oom_killed: boolean
  exit_code: number | null
  samples: number
}

export type ContainerUsageMap = Record<string, ContainerUsage>

export interface ContainerStats {
  name: string
  oom_killed: boolean
  restart_count: number
  has_healthcheck: boolean
  health_status: string
  // 0 means inspected and explicitly unlimited; null means the container was
  // gone by the post step so no limit could be read. The rules have to tell
  // those apart — "no limit set" is a finding, "we could not look" is not.
  mem_limit_bytes: number | null
  // Measured during the run by the daemon; null when the container was never
  // sampled (it lived entirely between two ticks) or the kernel did not expose
  // the counter. Null and 0 mean different things to the rules, so an
  // unmeasured container must not report 0.
  peak_rss_bytes: number | null
  peak_pids: number | null
  cpu_throttled_percent: number | null
  exit_code: number | null
  // False for a container that was still running when the job ended.
  observed: boolean
}

// Hand-written counterpart of the generated DockerBuildPayload, whose layer
// and container arrays are untyped dicts.
export interface DockerBuildPayload {
  workflow_run_id: number
  image_ref: string | null
  dockerfile_path: string | null
  image_size_bytes: number | null
  context_size_bytes: number | null
  build_duration_ms: number | null
  cache_hit_ratio: number | null
  layers: DockerLayer[] | null
  containers: ContainerStats[] | null
}

export interface GitHubContext {
  workflowRunId: number
  repository: string
  branch: string
  commitSha: string
  workflowName: string
}

export interface ActionState {
  daemonPid: number
  greensecopsUrl: string
  oidcToken: string
  workflowRunId: number
  repository: string
  runnerSpecs: RunnerSpecs
  startedAt: string
  // Image ids present before the job ran. The post step diffs against this to
  // find what the workflow built, so an image the runner image already shipped
  // is never reported as this build's output.
  preImageIds: string[]
}
