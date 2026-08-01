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

export interface ContainerStats {
  name: string
  oom_killed: boolean
  restart_count: number
  has_healthcheck: boolean
  health_status: string
  mem_limit_bytes: number
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
}
