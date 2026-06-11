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
}

export interface IngestPayload {
  workflow_run_id: number
  repository: string
  branch: string
  commit_sha: string
  workflow_name: string
  runner_specs: RunnerSpecs
  metrics: MetricsSample
  phase?: string
}

export interface SamplePayload {
  workflow_run_id: number
  cpu_percent?: number
  ram_used_mb?: number
  disk_used_gb?: number
  net_bytes_sent?: number
  net_bytes_recv?: number
}

export interface ActionState {
  daemonPid: number
  greensecopsUrl: string
  oidcToken: string
  workflowRunId: number
  repository: string
  startedAt: string
}
