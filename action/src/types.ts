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
