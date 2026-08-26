import type { Page, Route } from "@playwright/test"
import type {
  BillingSubscriptionPublic,
  DockerBuildTelemetryPublic,
  Engine,
  OverviewSection,
  PlanLimitsPublic,
  RepositoryPublic,
  UsagePublic,
  UserPublic,
} from "@/client"
import { ISSUE_CATEGORIES } from "@/lib/issue-constants"

// Mirrors the backend's severity-penalty weighting (app/services/scoring.py
// _SEVERITY_PENALTY) so mocked per-category scores/grades look realistic.
const MOCK_SEVERITY_PENALTY: Record<string, number> = {
  critical: 20,
  high: 10,
  medium: 5,
  low: 2,
  info: 0.5,
}
const MOCK_REPO_BASE_SCORE = 90

// ── Mock IDs ──────────────────────────────────────────────────────────
const ID = {
  user: "00000000-0000-0000-0000-000000000001",
  superuser: "00000000-0000-0000-0000-000000000002",
  org: "00000000-0000-0000-0000-000000000010",
  repo: "00000000-0000-0000-0000-000000000020",
  repoDisabled: "00000000-0000-0000-0000-000000000021",
  repoExternal: "00000000-0000-0000-0000-000000000022",
  repoNoAnalyses: "00000000-0000-0000-0000-000000000023",
  repoPrivate: "00000000-0000-0000-0000-000000000024",
  workflowFile: "00000000-0000-0000-0000-000000000030",
  workflowFileDeploy: "00000000-0000-0000-0000-000000000031",
  workflowFileRelease: "00000000-0000-0000-0000-000000000032",
  analysis: "00000000-0000-0000-0000-000000000040",
  analysisPending: "00000000-0000-0000-0000-000000000041",
  analysisFailed: "00000000-0000-0000-0000-000000000042",
  analysisInProgress: "00000000-0000-0000-0000-000000000043",
  analysisGradeA: "00000000-0000-0000-0000-000000000044",
  analysisGradeF: "00000000-0000-0000-0000-000000000045",
  issueSecurity: "00000000-0000-0000-0000-000000000050",
  issueReliability: "00000000-0000-0000-0000-000000000051",
  issueEnergy: "00000000-0000-0000-0000-000000000052",
  issueWithFix: "00000000-0000-0000-0000-000000000053",
  issueWithContext: "00000000-0000-0000-0000-000000000054",
  issueWithPendingFix: "00000000-0000-0000-0000-000000000055",
  issueWithFailedFix: "00000000-0000-0000-0000-000000000056",
  issueWithDeliveredFix: "00000000-0000-0000-0000-000000000057",
  ruleSecurity: "00000000-0000-0000-0000-000000000060",
  ruleReliability: "00000000-0000-0000-0000-000000000061",
  ruleDisabled: "00000000-0000-0000-0000-000000000062",
  fixReady: "00000000-0000-0000-0000-000000000070",
  fixDelivered: "00000000-0000-0000-0000-000000000071",
  fixPending: "00000000-0000-0000-0000-000000000072",
  fixFailed: "00000000-0000-0000-0000-000000000073",
  fixCommentDelivered: "00000000-0000-0000-0000-000000000074",
  fixMergedPr: "00000000-0000-0000-0000-000000000075",
  subscription: "00000000-0000-0000-0000-000000000080",
  subscriptionPro: "00000000-0000-0000-0000-000000000081",
  // Docker ids differ in their first 8 characters on purpose: dockerFixBranch()
  // (src/lib/delivery.ts) derives a PR branch from that slice, so same-prefixed
  // ids would give two targets the same branch.
  dockerTargetRoot: "0000a001-0000-0000-0000-000000000001",
  dockerTargetApi: "0000a002-0000-0000-0000-000000000002",
  dockerScan: "0000a010-0000-0000-0000-000000000010",
  dockerScanFailed: "0000a011-0000-0000-0000-000000000011",
  dockerFinding: "0000a020-0000-0000-0000-000000000020",
  dockerFix: "0000a030-0000-0000-0000-000000000030",
  dockerPr: "0000a040-0000-0000-0000-000000000040",
  dockerTelemetry: "0000a050-0000-0000-0000-000000000050",
  dockerTelemetryUnattributed: "0000a051-0000-0000-0000-000000000051",
  dockerRuntimeFinding: "0000a060-0000-0000-0000-000000000060",
  dockerRuntimeFindingUnattributed: "0000a061-0000-0000-0000-000000000061",
  // Same rule as the Docker ids above: ansibleFixBranch() slices the first 8
  // characters, so two projects sharing a prefix would share a PR branch.
  ansibleProjectDeploy: "0000b001-0000-0000-0000-000000000001",
  ansibleProjectRoles: "0000b002-0000-0000-0000-000000000002",
  ansibleScan: "0000b010-0000-0000-0000-000000000010",
  ansibleFinding: "0000b020-0000-0000-0000-000000000020",
  ansibleFindingFileLevel: "0000b021-0000-0000-0000-000000000021",
  ansibleFix: "0000b030-0000-0000-0000-000000000030",
}

// ── Users ─────────────────────────────────────────────────────────────
export const MOCK_USER = {
  id: ID.user,
  email: "user@example.com",
  full_name: "Test User",
  is_active: true,
  is_superuser: false,
  github_username: null,
  tier: "free" as const,
  created_at: "2024-01-01T00:00:00Z",
}

export const MOCK_SUPERUSER = {
  id: ID.superuser,
  email: "admin@example.com",
  full_name: "Admin User",
  is_active: true,
  is_superuser: true,
  github_username: "admin-gh",
  tier: "free" as const,
  created_at: "2024-01-01T00:00:00Z",
}

// ── Organizations ─────────────────────────────────────────────────────
export const MOCK_ORG = {
  id: ID.org,
  name: "acme-org",
  tier: "free" as const,
  default_llm_provider: null,
  default_llm_model: null,
  fix_delivery_mode: "pr" as const,
  created_at: "2024-01-01T00:00:00Z",
}

// ── Repositories ──────────────────────────────────────────────────────
export const MOCK_REPO = {
  id: ID.repo,
  org_id: ID.org,
  full_name: "acme/web-app",
  enabled: true,
  is_external: false,
  default_branch: "main",
  tier: "free" as const,
  created_at: "2024-01-01T00:00:00Z",
  avg_score: 82,
  grade: "B",
}

export const MOCK_REPO_DISABLED = {
  id: ID.repoDisabled,
  org_id: ID.org,
  full_name: "acme/old-service",
  enabled: false,
  is_external: false,
  default_branch: "main",
  tier: "free" as const,
  created_at: "2024-01-01T00:00:00Z",
  avg_score: null,
  grade: null,
}

export const MOCK_REPO_EXTERNAL = {
  id: ID.repoExternal,
  org_id: ID.org,
  full_name: "external/third-party-repo",
  enabled: true,
  is_external: true,
  default_branch: "main",
  tier: "free" as const,
  created_at: "2024-01-01T00:00:00Z",
  avg_score: 65,
  grade: "C",
}

export const MOCK_REPO_NO_ANALYSES = {
  id: ID.repoNoAnalyses,
  org_id: ID.org,
  full_name: "acme/new-repo",
  enabled: true,
  is_external: false,
  default_branch: "main",
  tier: "free" as const,
  created_at: "2024-06-01T00:00:00Z",
  avg_score: null,
  grade: null,
}

export const MOCK_REPO_PRIVATE = {
  id: ID.repoPrivate,
  org_id: ID.org,
  full_name: "acme/secret-service",
  enabled: true,
  is_external: false,
  is_private: true,
  default_branch: "main",
  tier: "free" as const,
  created_at: "2024-01-01T00:00:00Z",
  avg_score: 90,
  grade: "A",
}

// ── Workflow files ────────────────────────────────────────────────────
const WORKFLOW_RAW_CONTENT =
  "name: CI\non: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4"

export const MOCK_WORKFLOW_FILE = {
  id: ID.workflowFile,
  path: ".github/workflows/ci.yml",
  branch: "main",
  raw_content: WORKFLOW_RAW_CONTENT,
  source_commit_sha: "abc1234def5678901234567890abcdef12345678",
  fetched_at: "2026-01-01T00:00:00Z",
}

export const MOCK_WORKFLOW_FILE_DEPLOY = {
  id: ID.workflowFileDeploy,
  path: ".github/workflows/deploy.yml",
  branch: "main",
  raw_content: WORKFLOW_RAW_CONTENT,
  source_commit_sha: "abc1234def5678901234567890abcdef12345678",
  fetched_at: "2026-01-01T00:00:00Z",
}

// ── Pull requests (PullRequestPublic) ─────────────────────────────────
export const MOCK_PR_OPEN = {
  id: "00000000-0000-0000-0000-000000000090",
  repo_id: ID.repo,
  pr_branch: "greensecops/fixes-wf-00000000",
  pr_url: "https://github.com/acme/web-app/pull/42",
  pr_state: "open" as const,
  ci_status: "success" as const,
  review_decision: "approved" as const,
  mergeable_state: "clean",
  externally_modified: false,
  comment_url: null,
  created_at: "2024-01-02T10:03:00Z",
  updated_at: "2024-01-02T10:04:00Z",
}

// ── Docker (targets, files, findings, fixes, scans) ───────────────────
const DOCKERFILE_RAW_CONTENT =
  'FROM node:latest\nRUN apt-get update && apt-get install -y curl\nCOPY . /app\nCMD ["node", "index.js"]'

export const MOCK_DOCKER_TARGET = {
  id: ID.dockerTargetRoot,
  repo_id: ID.repo,
  repo_full_name: "acme/web-app",
  root_path: "",
  enabled: true,
  last_scanned_at: "2024-01-02T10:00:00Z",
  last_scanned_head_sha: "abc1234",
  latest_score: 72,
  latest_grade: "C",
  badge_sig: "sig-root",
}

export const MOCK_DOCKER_TARGET_API = {
  id: ID.dockerTargetApi,
  repo_id: ID.repo,
  repo_full_name: "acme/web-app",
  root_path: "services/api",
  enabled: true,
  last_scanned_at: null,
  last_scanned_head_sha: null,
  latest_score: null,
  latest_grade: "E",
  badge_sig: "sig-api",
}

export const MOCK_DOCKER_FILE = {
  path: "Dockerfile",
  raw_content: DOCKERFILE_RAW_CONTENT,
  kind: "dockerfile",
}

export const MOCK_DOCKER_FINDING = {
  id: ID.dockerFinding,
  scan_id: ID.dockerScan,
  docker_target_id: ID.dockerTargetRoot,
  rule_id: ID.ruleReliability,
  rule_slug: "unpinned-base-image",
  file_path: "Dockerfile",
  service_name: null,
  stage_name: null,
  line_start: 1,
  line_end: 1,
  severity: "high" as const,
  category: "reliability" as const,
  message: "Base image node:latest is not pinned to a digest",
  context: null,
  status: "open" as const,
  fix_id: null,
  fix_status: null,
  created_at: "2024-01-02T10:00:00Z",
  resolved_at: null,
}

export const MOCK_DOCKER_FIX = {
  id: ID.dockerFix,
  docker_target_id: ID.dockerTargetRoot,
  file_path: "Dockerfile",
  pr_id: null,
  llm_provider: "openai" as const,
  llm_model: "gpt-4o",
  status: "ready" as const,
  full_content: 'FROM node:22-alpine\nCOPY . /app\nCMD ["node", "index.js"]',
  error_message: null,
  pr_url: null,
  pr_branch: null,
  pr_state: null,
  created_at: "2024-01-02T10:02:00Z",
  delivered_at: null,
}

// ── Ansible ───────────────────────────────────────────────────────────
// The offending task is the real one from this repo's own deployment: an ECR
// login whose shell command interpolates a variable without quoting it.
const ANSIBLE_RAW_CONTENT = `---
- name: Log in to ECR
  ansible.builtin.shell:
    cmd: docker login -u AWS {{ registry }} --region {{ greensecops_region }}
  changed_when: false
  become: true
`

export const MOCK_ANSIBLE_PROJECT = {
  id: ID.ansibleProjectDeploy,
  repo_id: ID.repo,
  repo_full_name: "acme/web-app",
  // "" is legal for this engine and means the repository root, unlike Terraform.
  root_path: "",
  enabled: true,
  last_scanned_at: "2024-01-02T10:00:00Z",
  last_scanned_head_sha: "abc1234",
  latest_score: 68,
  latest_grade: "C",
  badge_sig: "sig-ansible-root",
}

export const MOCK_ANSIBLE_PROJECT_ROLES = {
  id: ID.ansibleProjectRoles,
  repo_id: ID.repo,
  repo_full_name: "acme/web-app",
  root_path: "deploy/ansible",
  enabled: true,
  last_scanned_at: null,
  last_scanned_head_sha: null,
  latest_score: null,
  latest_grade: null,
  badge_sig: "sig-ansible-roles",
}

export const MOCK_ANSIBLE_FILE = {
  path: "roles/docker/tasks/main.yml",
  raw_content: ANSIBLE_RAW_CONTENT,
  kind: "tasks",
}

export const MOCK_ANSIBLE_FINDING = {
  id: ID.ansibleFinding,
  scan_id: ID.ansibleScan,
  ansible_project_id: ID.ansibleProjectDeploy,
  rule_id: ID.ruleSecurity,
  rule_slug: "shell_with_unquoted_variable",
  file_path: "roles/docker/tasks/main.yml",
  task_name: "Log in to ECR",
  line_start: 2,
  line_end: 6,
  severity: "high" as const,
  category: "security" as const,
  message: "Shell command interpolates {{ registry }} without quoting it.",
  context: null,
  status: "open" as const,
  fix_id: null,
  fix_status: null,
  created_at: "2024-01-02T10:00:00Z",
  resolved_at: null,
}

// A finding about the file rather than a task: no task name, no line. The
// FileViewer groups these under their own heading, so the mock keeps the case
// that would otherwise render nowhere.
export const MOCK_ANSIBLE_FINDING_FILE_LEVEL = {
  ...MOCK_ANSIBLE_FINDING,
  id: ID.ansibleFindingFileLevel,
  rule_slug: "galaxy_requirement_unpinned",
  task_name: null,
  line_start: null,
  line_end: null,
  severity: "medium" as const,
  category: "reliability" as const,
  message: "Collection community.docker is not pinned to a version.",
}

export const MOCK_ANSIBLE_FIX = {
  id: ID.ansibleFix,
  ansible_project_id: ID.ansibleProjectDeploy,
  file_path: "roles/docker/tasks/main.yml",
  pr_id: null,
  llm_provider: "openai" as const,
  llm_model: "gpt-4o",
  status: "ready" as const,
  // The fix the rule asks for: quote both interpolations, change nothing else.
  full_content: ANSIBLE_RAW_CONTENT.replace(
    "{{ registry }} --region {{ greensecops_region }}",
    "{{ registry | quote }} --region {{ greensecops_region | quote }}",
  ),
  error_message: null,
  pr_url: null,
  pr_branch: null,
  pr_state: null,
  created_at: "2024-01-02T10:02:00Z",
  delivered_at: null,
}

export const MOCK_ANSIBLE_SCAN = {
  id: ID.ansibleScan,
  ansible_project_id: ID.ansibleProjectDeploy,
  status: "completed" as const,
  triggered_by: "manual" as const,
  branch: "main",
  commit_sha: "abc1234",
  score: 68,
  grade: "C",
  file_count: 3,
  error_message: null,
  failure_kind: null,
  created_at: "2024-01-02T10:00:00Z",
  completed_at: "2024-01-02T10:00:30Z",
}

export const MOCK_DOCKER_SCAN = {
  id: ID.dockerScan,
  docker_target_id: ID.dockerTargetRoot,
  status: "completed" as const,
  triggered_by: "manual" as const,
  branch: "main",
  commit_sha: "abc1234",
  score: 72,
  grade: "C",
  file_count: 2,
  error_message: null,
  created_at: "2024-01-02T10:00:00Z",
  completed_at: "2024-01-02T10:00:30Z",
}

export const MOCK_DOCKER_SCAN_FAILED = {
  ...MOCK_DOCKER_SCAN,
  id: ID.dockerScanFailed,
  status: "failed" as const,
  triggered_by: "webhook" as const,
  score: null,
  grade: null,
  file_count: null,
  error_message: "Could not fetch Docker files from GitHub",
  completed_at: "2024-01-01T09:00:10Z",
  created_at: "2024-01-01T09:00:00Z",
}

export const MOCK_DOCKER_RUNTIME_FINDING = {
  id: ID.dockerRuntimeFinding,
  telemetry_id: ID.dockerTelemetry,
  rule_slug: "container_unbounded_memory",
  rule_title: "Container ran with no memory limit",
  severity: "medium" as const,
  category: "energy" as const,
  evidence: "container 'api' peaked at 420 MB with no memory limit set",
  recommendation:
    "Set a memory limit for 'api' — measured peak was 420 MB, so a limit around 630 MB leaves headroom.",
  created_at: "2024-01-02T10:05:00Z",
}

export const MOCK_DOCKER_RUNTIME_BUILD: DockerBuildTelemetryPublic = {
  id: ID.dockerTelemetry,
  workflow_run_id: 12345678901,
  image_ref: "sha256:abc",
  dockerfile_path: "Dockerfile",
  image_size_bytes: 2_400_000_000,
  context_size_bytes: 900_000_000,
  build_duration_ms: null,
  cache_hit_ratio: 0.18,
  layers: [{ index: 0, size_bytes: 500_000_000, instruction: "RUN" }],
  containers: [
    {
      name: "api",
      oom_killed: false,
      restart_count: 0,
      has_healthcheck: true,
      health_status: "healthy",
      // 0 is "inspected and explicitly unlimited" — what the finding fires on.
      mem_limit_bytes: 0,
      peak_rss_bytes: 420_000_000,
      peak_pids: 12,
      cpu_throttled_percent: null,
      exit_code: null,
      observed: true,
    },
  ],
  collected_at: "2024-01-02T10:05:00Z",
  findings: [MOCK_DOCKER_RUNTIME_FINDING],
}

// A build reported without the action's dockerfile_path input: its findings
// are real but cannot drive a fix, because nothing names a file to rewrite.
export const MOCK_DOCKER_RUNTIME_BUILD_UNATTRIBUTED: DockerBuildTelemetryPublic =
  {
    ...MOCK_DOCKER_RUNTIME_BUILD,
    id: ID.dockerTelemetryUnattributed,
    dockerfile_path: null,
    findings: [
      {
        ...MOCK_DOCKER_RUNTIME_FINDING,
        id: ID.dockerRuntimeFindingUnattributed,
        telemetry_id: ID.dockerTelemetryUnattributed,
      },
    ],
  }

// Branch mirrors dockerFixBranch(ID.dockerTargetRoot) in src/lib/delivery.ts,
// which is what the Docker PRs tab filters and maps on.
export const MOCK_DOCKER_PR = {
  id: ID.dockerPr,
  repo_id: ID.repo,
  pr_branch: `greensecops/docker-${ID.dockerTargetRoot.slice(0, 8)}`,
  pr_url: "https://github.com/acme/web-app/pull/77",
  pr_state: "open" as const,
  ci_status: "success" as const,
  review_decision: "approved" as const,
  mergeable_state: "clean",
  externally_modified: false,
  comment_url: null,
  created_at: "2024-01-02T10:03:00Z",
  updated_at: "2024-01-02T10:04:00Z",
}

// ── Analyses ──────────────────────────────────────────────────────────
export const MOCK_ANALYSIS = {
  id: ID.analysis,
  repo_id: ID.repo,
  workflow_file_id: ID.workflowFile,
  file_path: ".github/workflows/ci.yml",
  repo_full_name: "acme/web-app",
  content_hash: "abc123",
  status: "completed" as const,
  score: 82,
  grade: "B",
  triggered_by: "manual" as const,
  branch: "main",
  commit_sha: "a1b2c3d4e5f6",
  created_at: "2024-01-02T10:00:00Z",
  completed_at: "2024-01-02T10:01:00Z",
}

export const MOCK_ANALYSIS_PENDING = {
  ...MOCK_ANALYSIS,
  id: ID.analysisPending,
  status: "pending" as const,
  score: null,
  grade: null,
  completed_at: null,
}

export const MOCK_ANALYSIS_FAILED = {
  ...MOCK_ANALYSIS,
  id: ID.analysisFailed,
  status: "failed" as const,
  score: null,
  grade: null,
  error_message: "Failed to fetch workflow files",
}

export const MOCK_ANALYSIS_IN_PROGRESS = {
  ...MOCK_ANALYSIS,
  id: ID.analysisInProgress,
  status: "in_progress" as const,
  score: null,
  grade: null,
  completed_at: null,
}

export const MOCK_ANALYSIS_GRADE_A = {
  ...MOCK_ANALYSIS,
  id: ID.analysisGradeA,
  score: 100,
  grade: "A",
}

export const MOCK_ANALYSIS_GRADE_F = {
  ...MOCK_ANALYSIS,
  id: ID.analysisGradeF,
  score: 12,
  grade: "F",
}

// ── Issues ─────────────────────────────────────────────────────────────
export const MOCK_ISSUE_SECURITY = {
  id: ID.issueSecurity,
  analysis_id: ID.analysis,
  rule_id: ID.ruleSecurity,
  rule_slug: "excessive_token_permissions",
  severity: "critical" as const,
  category: "security" as const,
  line_start: 5,
  line_end: 5,
  message: "Workflow uses overly permissive token permissions.",
  context: null,
  created_at: "2024-01-02T10:01:00Z",
  fix_id: null,
  fix_status: null,
  file_path: ".github/workflows/ci.yml",
}

export const MOCK_ISSUE_RELIABILITY = {
  id: ID.issueReliability,
  analysis_id: ID.analysis,
  rule_id: ID.ruleReliability,
  rule_slug: "missing_timeout",
  severity: "high" as const,
  category: "reliability" as const,
  line_start: 12,
  line_end: 12,
  message: "Job 'build' has no timeout-minutes set.",
  context: null,
  created_at: "2024-01-02T10:01:00Z",
  fix_id: null,
  fix_status: null,
  file_path: ".github/workflows/ci.yml",
}

export const MOCK_ISSUE_ENERGY = {
  id: ID.issueEnergy,
  analysis_id: ID.analysis,
  rule_id: "00000000-0000-0000-0000-000000000063",
  rule_slug: "caching_missing",
  severity: "medium" as const,
  category: "energy" as const,
  line_start: 20,
  line_end: 25,
  message: "No caching configured for dependencies.",
  context: null,
  created_at: "2024-01-02T10:01:00Z",
  fix_id: null,
  fix_status: null,
  file_path: ".github/workflows/ci.yml",
}

export const MOCK_ISSUE_WITH_FIX = {
  id: ID.issueWithFix,
  analysis_id: ID.analysis,
  rule_id: ID.ruleReliability,
  rule_slug: "missing_timeout",
  severity: "high" as const,
  category: "reliability" as const,
  line_start: 30,
  line_end: 30,
  message: "Job 'test' has no timeout-minutes set.",
  context: null,
  created_at: "2024-01-02T10:01:00Z",
  fix_id: ID.fixReady,
  fix_status: "ready" as const,
  file_path: ".github/workflows/ci.yml",
}

export const MOCK_ISSUE_WITH_CONTEXT = {
  id: ID.issueWithContext,
  analysis_id: ID.analysis,
  rule_id: ID.ruleReliability,
  rule_slug: "missing_timeout",
  severity: "high" as const,
  category: "reliability" as const,
  line_start: 12,
  line_end: 14,
  message: "Job 'build' has no timeout-minutes set.",
  context: "  build:\n    runs-on: ubuntu-latest\n    steps:",
  created_at: "2024-01-02T10:01:00Z",
  fix_id: null,
  fix_status: null,
  file_path: ".github/workflows/ci.yml",
}

export const MOCK_ISSUE_WITH_PENDING_FIX = {
  id: ID.issueWithPendingFix,
  analysis_id: ID.analysis,
  rule_id: ID.ruleSecurity,
  rule_slug: "excessive_token_permissions",
  severity: "critical" as const,
  category: "security" as const,
  line_start: 5,
  line_end: 5,
  message: "Workflow uses overly permissive token permissions.",
  context: null,
  created_at: "2024-01-02T10:01:00Z",
  fix_id: ID.fixPending,
  fix_status: "pending" as const,
  file_path: ".github/workflows/ci.yml",
}

export const MOCK_ISSUE_WITH_FAILED_FIX = {
  id: ID.issueWithFailedFix,
  analysis_id: ID.analysis,
  rule_id: ID.ruleReliability,
  rule_slug: "missing_timeout",
  severity: "high" as const,
  category: "reliability" as const,
  line_start: 20,
  line_end: 20,
  message: "Job 'lint' has no timeout-minutes set.",
  context: null,
  created_at: "2024-01-02T10:01:00Z",
  fix_id: ID.fixFailed,
  fix_status: "failed" as const,
  file_path: ".github/workflows/ci.yml",
}

export const MOCK_ISSUE_WITH_DELIVERED_FIX = {
  id: ID.issueWithDeliveredFix,
  analysis_id: ID.analysis,
  rule_id: ID.ruleReliability,
  rule_slug: "missing_timeout",
  severity: "high" as const,
  category: "reliability" as const,
  line_start: 25,
  line_end: 25,
  message: "Job 'deploy' has no timeout-minutes set.",
  context: null,
  created_at: "2024-01-02T10:01:00Z",
  fix_id: ID.fixDelivered,
  fix_status: "delivered" as const,
  file_path: ".github/workflows/ci.yml",
}

// ── Fixes ──────────────────────────────────────────────────────────────
const SAMPLE_BASE_CONTENT =
  "name: CI\non: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4"
const SAMPLE_FULL_CONTENT =
  "name: CI\non: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n    timeout-minutes: 30\n    steps:\n      - uses: actions/checkout@v4"
const SAMPLE_DIFF_PATCH =
  "--- a/.github/workflows/ci.yml\n+++ b/.github/workflows/ci.yml\n@@ -4,6 +4,7 @@\n jobs:\n   build:\n     runs-on: ubuntu-latest\n+    timeout-minutes: 30\n     steps:\n       - uses: actions/checkout@v4"

export const MOCK_FIX_READY = {
  id: ID.fixReady,
  workflow_file_id: ID.workflowFile,
  file_path: ".github/workflows/ci.yml",
  repo_id: ID.repo,
  pr_id: null,
  llm_provider: "openai" as const,
  llm_model: "gpt-4o-mini",
  status: "ready" as const,
  full_content: SAMPLE_FULL_CONTENT,
  base_content: SAMPLE_BASE_CONTENT,
  error_message: null,
  pr_url: null,
  pr_branch: null,
  pr_state: null,
  created_at: "2024-01-02T10:02:00Z",
  delivered_at: null,
  issues: [
    {
      id: ID.issueWithFix,
      rule_slug: "missing_timeout",
      severity: "high" as const,
      category: "reliability" as const,
      message: "Job 'test' has no timeout-minutes set.",
      line_start: 30,
      line_end: 30,
    },
  ],
}

export const MOCK_FIX_DELIVERED = {
  id: ID.fixDelivered,
  workflow_file_id: ID.workflowFileDeploy,
  file_path: ".github/workflows/deploy.yml",
  repo_id: ID.repo,
  pr_id: "00000000-0000-0000-0000-000000000090",
  llm_provider: "openai" as const,
  llm_model: "gpt-4o-mini",
  status: "delivered" as const,
  full_content: SAMPLE_FULL_CONTENT,
  base_content: SAMPLE_BASE_CONTENT,
  error_message: null,
  pr_url: "https://github.com/acme/web-app/pull/42",
  pr_branch: "greensecops/fixes-wf-deploy",
  pr_state: "open",
  created_at: "2024-01-02T10:02:00Z",
  delivered_at: "2024-01-02T10:03:00Z",
  issues: [
    {
      id: ID.issueReliability,
      rule_slug: "missing_timeout",
      severity: "high" as const,
      category: "reliability" as const,
      message: "Job 'build' has no timeout-minutes set.",
      line_start: 12,
      line_end: 12,
    },
  ],
}

export const MOCK_FIX_PENDING = {
  id: ID.fixPending,
  workflow_file_id: ID.workflowFileRelease,
  file_path: ".github/workflows/release.yml",
  repo_id: ID.repo,
  pr_id: null,
  llm_provider: "openai" as const,
  llm_model: "gpt-4o-mini",
  status: "pending" as const,
  full_content: null,
  base_content: SAMPLE_BASE_CONTENT,
  error_message: null,
  pr_url: null,
  pr_branch: null,
  pr_state: null,
  created_at: "2024-01-02T10:02:00Z",
  delivered_at: null,
  issues: [
    {
      id: ID.issueSecurity,
      rule_slug: "excessive_token_permissions",
      severity: "critical" as const,
      category: "security" as const,
      message: "Workflow uses overly permissive token permissions.",
      line_start: 5,
      line_end: 5,
    },
  ],
}

export const MOCK_FIX_FAILED = {
  id: ID.fixFailed,
  issue_id: ID.issueWithFailedFix,
  llm_provider: "openai" as const,
  llm_model: "gpt-4o-mini",
  status: "failed" as const,
  diff: null,
  diff_patch: null,
  pr_url: null,
  pr_branch: null,
  pr_state: null,
  comment_url: null,
  error_message: "LLM API timeout after 30s",
  created_at: "2024-01-02T10:02:00Z",
  delivered_at: null,
  rule_slug: "missing_timeout",
  severity: "high" as const,
  category: "reliability" as const,
  message: "Job 'lint' has no timeout-minutes set.",
  line_start: 20,
  line_end: 20,
  file_path: ".github/workflows/ci.yml",
}

export const MOCK_FIX_COMMENT_DELIVERED = {
  id: ID.fixCommentDelivered,
  issue_id: ID.issueWithDeliveredFix,
  llm_provider: "openai" as const,
  llm_model: "gpt-4o-mini",
  status: "delivered" as const,
  diff: null,
  diff_patch: SAMPLE_DIFF_PATCH,
  pr_url: null,
  pr_branch: null,
  pr_state: null,
  comment_url: "https://github.com/acme/web-app/issues/5#issuecomment-9876543",
  created_at: "2024-01-02T10:02:00Z",
  delivered_at: "2024-01-02T10:04:00Z",
  rule_slug: "missing_timeout",
  severity: "high" as const,
  category: "reliability" as const,
  message: "Job 'deploy' has no timeout-minutes set.",
  line_start: 25,
  line_end: 25,
  file_path: ".github/workflows/ci.yml",
}

export const MOCK_FIX_MERGED_PR = {
  id: ID.fixMergedPr,
  issue_id: ID.issueReliability,
  llm_provider: "openai" as const,
  llm_model: "gpt-4o-mini",
  status: "delivered" as const,
  diff: null,
  diff_patch: SAMPLE_DIFF_PATCH,
  pr_url: "https://github.com/acme/web-app/pull/10",
  pr_branch: "greensecops/fix-missing-timeout-deploy",
  pr_state: "merged",
  comment_url: null,
  created_at: "2024-01-01T09:00:00Z",
  delivered_at: "2024-01-01T09:01:00Z",
  rule_slug: "missing_timeout",
  severity: "high" as const,
  category: "reliability" as const,
  message: "Job 'build' has no timeout-minutes set.",
  line_start: 12,
  line_end: 12,
  file_path: ".github/workflows/ci.yml",
}

// ── Rules ──────────────────────────────────────────────────────────────
export const MOCK_RULE_SECURITY = {
  id: ID.ruleSecurity,
  slug: "excessive_token_permissions",
  category: "security" as const,
  severity: "critical" as const,
  title: "Excessive Token Permissions",
  description:
    "Workflow uses overly permissive GITHUB_TOKEN permissions. Restrict to least privilege.",
  enabled: true,
}

export const MOCK_RULE_RELIABILITY = {
  id: ID.ruleReliability,
  slug: "missing_timeout",
  category: "reliability" as const,
  severity: "high" as const,
  title: "Missing Timeout",
  description:
    "Jobs without timeout-minutes can run indefinitely, consuming resources.",
  enabled: true,
}

export const MOCK_RULE_DISABLED = {
  id: ID.ruleDisabled,
  slug: "caching_missing",
  category: "energy" as const,
  severity: "medium" as const,
  title: "Caching Missing",
  description:
    "No caching configured for dependencies. This wastes energy on repeated downloads.",
  enabled: false,
}

// ── Billing ────────────────────────────────────────────────────────────
// Limits mirror backend/app/core/plans.py. They are pinned there by
// tests/services/billing/test_usage.py and rendered into the marketing page by
// scripts/render_landing_pricing.py, so these three places agree by
// construction rather than by anyone remembering.
export const MOCK_PLANS = [
  {
    tier: "free" as const,
    name: "Free",
    price_cents: 0,
    price_display: "$0/mo",
    tagline: "Personal projects and evaluation. No credit card required.",
    limits: { analyses: 100, fixes: 10, repos: 3 },
    auto_fix: false,
    public_repos_only: false,
    is_purchasable: false,
    features: ["Full five-pillar grading"],
  },
  {
    tier: "starter" as const,
    name: "Starter",
    price_cents: 1900,
    price_display: "$19/mo",
    tagline: "Small teams and growing solo developers.",
    limits: { analyses: 1000, fixes: 100, repos: 20 },
    auto_fix: true,
    public_repos_only: false,
    is_purchasable: true,
    features: ["Automatic fix pull requests"],
  },
  {
    tier: "pro" as const,
    name: "Pro",
    price_cents: 7900,
    price_display: "$79/mo",
    tagline: "Growing teams that need higher limits and faster support.",
    limits: { analyses: 10000, fixes: 1000, repos: 100 },
    auto_fix: true,
    public_repos_only: false,
    is_purchasable: true,
    features: ["Priority email support"],
  },
  {
    tier: "ultimate" as const,
    name: "Ultimate",
    price_cents: 29900,
    price_display: "$299/mo",
    tagline: "Large organisations with unlimited need.",
    limits: { analyses: null, fixes: null, repos: null },
    auto_fix: true,
    public_repos_only: false,
    is_purchasable: true,
    features: ["Unlimited everything"],
  },
  {
    tier: "open_source" as const,
    name: "Open Source",
    price_cents: 0,
    price_display: "Free",
    tagline: "For qualifying public open-source projects.",
    limits: { analyses: 2000, fixes: 300, repos: null },
    auto_fix: true,
    public_repos_only: true,
    is_purchasable: false,
    features: ["OSS badge for your README"],
  },
]

export const MOCK_SUBSCRIPTION: BillingSubscriptionPublic = {
  id: ID.subscription,
  tier: "free" as const,
  effective_tier: "free" as const,
  status: "active" as const,
  analyses_used: 12,
  fixes_used: 2,
  repos_used: 1,
  period_start: "2026-08-01T00:00:00Z",
  period_end: "2026-09-01T00:00:00Z",
  grace_expires_at: null,
  cancel_at_period_end: false,
  trial_end: null,
  billing_enabled: true,
}

export const MOCK_USAGE: UsagePublic = {
  period_start: "2026-08-01T00:00:00Z",
  period_end: "2026-09-01T00:00:00Z",
  analyses_used: 12,
  fixes_used: 2,
  repos_used: 1,
  limits: { analyses: 100, fixes: 10, repos: 3 },
  breakdown: [
    { meter: "analyses", engine: "terraform", quantity: 7 },
    { meter: "analyses", engine: "workflow", quantity: 5 },
    { meter: "fixes", engine: "workflow", quantity: 2 },
  ],
}

export const MOCK_TIER_LIMITS: { tier: string; limits: PlanLimitsPublic } = {
  tier: "free",
  limits: { analyses: 100, fixes: 10, repos: 3 },
}

export const MOCK_SUBSCRIPTION_PRO: BillingSubscriptionPublic = {
  ...MOCK_SUBSCRIPTION,
  id: ID.subscriptionPro,
  tier: "pro" as const,
  effective_tier: "pro" as const,
  analyses_used: 5,
  fixes_used: 10,
  repos_used: 2,
}

export const MOCK_USAGE_PRO: UsagePublic = {
  ...MOCK_USAGE,
  analyses_used: 5,
  fixes_used: 10,
  repos_used: 2,
  limits: { analyses: 10000, fixes: 1000, repos: 100 },
}

export const MOCK_TIER_LIMITS_PRO: { tier: string; limits: PlanLimitsPublic } =
  {
    tier: "pro",
    limits: { analyses: 10000, fixes: 1000, repos: 100 },
  }

export const MOCK_SUBSCRIPTION_AT_LIMIT: BillingSubscriptionPublic = {
  ...MOCK_SUBSCRIPTION,
  analyses_used: 100,
  fixes_used: 10,
  repos_used: 3,
}

export const MOCK_USAGE_AT_LIMIT: UsagePublic = {
  ...MOCK_USAGE,
  analyses_used: 100,
  fixes_used: 10,
  repos_used: 3,
}

// A Pro subscription whose payment failed. Still fully entitled — the grace
// window is the whole point — but the UI must say so.
export const MOCK_SUBSCRIPTION_PAST_DUE: BillingSubscriptionPublic = {
  ...MOCK_SUBSCRIPTION_PRO,
  status: "past_due" as const,
  grace_expires_at: "2099-01-10T00:00:00Z",
}

// Grace expired: still a Pro subscription, but metered at Free.
export const MOCK_SUBSCRIPTION_UNPAID: BillingSubscriptionPublic = {
  ...MOCK_SUBSCRIPTION_PRO,
  status: "unpaid" as const,
  effective_tier: "free" as const,
  grace_expires_at: "2020-01-10T00:00:00Z",
}

export const MOCK_INVOICES = [
  {
    id: ID.subscription,
    stripe_invoice_id: "in_test_1",
    number: "GS-0001",
    status: "paid" as const,
    amount_due_cents: 7900,
    amount_paid_cents: 7900,
    currency: "usd",
    hosted_invoice_url: "https://invoice.stripe.com/i/test",
    invoice_pdf: null,
    period_start: "2026-08-01T00:00:00Z",
    period_end: "2026-09-01T00:00:00Z",
    paid_at: "2026-08-01T00:00:00Z",
    created_at: "2026-08-01T00:00:00Z",
  },
]

// ── AI Providers ───────────────────────────────────────────────────────
export const MOCK_AI_PROVIDERS = {
  providers: [
    {
      id: "openai",
      name: "OpenAI",
      default_model: "gpt-4o-mini",
      models: ["gpt-4o", "gpt-4o-mini"],
    },
    {
      id: "anthropic",
      name: "Anthropic",
      default_model: "claude-sonnet-4-20250514",
      models: ["claude-sonnet-4-20250514", "claude-haiku-4-5-20251001"],
    },
  ],
}

// ── Installations (returns OrganizationPublic[]) ──────────────────────
export const MOCK_INSTALLATION = {
  id: ID.org,
  name: "acme-org",
  tier: "free" as const,
  default_llm_provider: null,
  default_llm_model: null,
  fix_delivery_mode: "pr" as const,
  created_at: "2024-01-01T00:00:00Z",
}

// ── Route mock helpers ─────────────────────────────────────────────────

export async function mockUserMe(
  page: Page,
  user: UserPublic = MOCK_SUPERUSER,
) {
  await page.route("**/api/v1/users/me", (route) => {
    route.fulfill({ json: user })
  })
}

export async function mockRepositories(
  page: Page,
  repos: RepositoryPublic[] = [MOCK_REPO],
) {
  // `/workflow-files` moved to `/workflow/repositories/{id}/files`, so it needs
  // its own glob rather than riding along under `/repositories`.
  await page.route("**/api/v1/workflow/repositories/*/files*", (route) => {
    route.fulfill({ json: [MOCK_WORKFLOW_FILE] })
  })
  await page.route("**/api/v1/repositories**", (route) => {
    const url = route.request().url()
    const method = route.request().method()
    // PATCH first: it addresses `/repositories/{id}`, which the by-id GET
    // branch below would otherwise answer with an unchanged repo.
    if (method === "PATCH") {
      const repo = repos[0]
      route.fulfill({ json: { ...repo, enabled: !repo.enabled } })
    } else if (url.includes("/workflow-sync")) {
      route.fulfill({
        json: {
          branch: "main",
          head_sha: "abc1234def5678901234567890abcdef12345678",
          added: 1,
          updated: 2,
          unchanged: 3,
          restored: 0,
          deleted: 1,
          skipped_stale: 0,
        },
      })
    } else if (url.match(/\/repositories\/[0-9a-f-]{36}$/)) {
      const id = url.split("/").pop()
      const repo = repos.find((r) => r.id === id) ?? repos[0]
      route.fulfill({ json: repo })
    } else if (url.includes("/action-integration")) {
      route.fulfill({
        json: { pr_url: "https://github.com/acme/web-app/pull/99" },
      })
    } else if (url.includes("/branches")) {
      route.fulfill({ json: ["main"] })
    } else {
      route.fulfill({ json: repos })
    }
  })
}

export async function mockAnalyses(page: Page, analyses = [MOCK_ANALYSIS]) {
  await page.route("**/api/v1/workflow/scans**", (route) => {
    const url = route.request().url()
    const method = route.request().method()
    if (method === "POST" && url.includes("/repositories/")) {
      route.fulfill({
        status: 202,
        json: { status: "queued", repo_id: MOCK_REPO.id },
      })
    } else if (url.match(/\/scans\/[0-9a-f-]{36}$/)) {
      const id = url.split("/").pop()
      const analysis = analyses.find((a) => a.id === id) ?? analyses[0]
      route.fulfill({ json: analysis })
    } else {
      route.fulfill({ json: analyses })
    }
  })
}

export async function mockIssues(
  page: Page,
  issues = [MOCK_ISSUE_SECURITY, MOCK_ISSUE_RELIABILITY, MOCK_ISSUE_ENERGY],
  analyses: Array<{ id: string; repo_id: string }> = [MOCK_ANALYSIS],
) {
  await page.route("**/api/v1/workflow/findings**", (route) => {
    const url = route.request().url()
    if (url.includes("/findings/stats")) {
      // Mirrors the backend's SQL-aggregated shape (open/resolved/critical_open
      // per category, plus a nested per-repo breakdown for the dashboard's
      // star diagram), computed from the same fixture list the dashboard's
      // other issue-driven assertions use.
      const active = issues.filter(
        (i) => !(i as { ignored_at?: string | null }).ignored_at,
      )
      type Bucket = { open: number; resolved: number; critical_open: number }
      const byCategory = new Map<string, Bucket>()
      type RepoCategoryBucket = {
        open: number
        critical_open: number
        penalty: number
      }
      const byRepo = new Map<string, Map<string, RepoCategoryBucket>>()
      const analysisToRepo = new Map(analyses.map((a) => [a.id, a.repo_id]))
      for (const i of active as Array<{
        analysis_id: string
        category: string
        severity: string
        resolved_at?: string | null
      }>) {
        const entry = byCategory.get(i.category) ?? {
          open: 0,
          resolved: 0,
          critical_open: 0,
        }
        if (i.resolved_at) {
          entry.resolved += 1
        } else {
          entry.open += 1
          if (i.severity === "critical") entry.critical_open += 1

          const repoId = analysisToRepo.get(i.analysis_id)
          if (repoId) {
            const categories =
              byRepo.get(repoId) ?? new Map<string, RepoCategoryBucket>()
            const repoEntry = categories.get(i.category) ?? {
              open: 0,
              critical_open: 0,
              penalty: 0,
            }
            repoEntry.open += 1
            if (i.severity === "critical") repoEntry.critical_open += 1
            repoEntry.penalty += MOCK_SEVERITY_PENALTY[i.severity] ?? 5
            categories.set(i.category, repoEntry)
            byRepo.set(repoId, categories)
          }
        }
        byCategory.set(i.category, entry)
      }
      const byCategoryList = Array.from(byCategory.entries()).map(
        ([category, bucket]) => ({ category, ...bucket }),
      )
      // Per-category score deviates from a fixed repo baseline by how far its
      // penalty sits from the mean across all 5 categories, so the 5 scores
      // always average back to the repo's own score — same invariant the
      // real backend enforces (app/services/scoring.py compute_category_scores).
      const byRepoList = Array.from(byRepo.entries()).map(
        ([repoId, categories]) => {
          const penalties = ISSUE_CATEGORIES.map(
            (c) => categories.get(c)?.penalty ?? 0,
          )
          const meanPenalty =
            penalties.reduce((sum, p) => sum + p, 0) / penalties.length
          const categoryStats = ISSUE_CATEGORIES.map((category) => {
            const bucket = categories.get(category)
            const penalty = bucket?.penalty ?? 0
            const score = Math.max(
              0,
              Math.min(100, MOCK_REPO_BASE_SCORE - (penalty - meanPenalty)),
            )
            return {
              category,
              open: bucket?.open ?? 0,
              critical_open: bucket?.critical_open ?? 0,
              score,
              grade: "B",
            }
          })
          return {
            repo_id: repoId,
            score: MOCK_REPO_BASE_SCORE,
            grade: "A+",
            categories: categoryStats,
          }
        },
      )
      route.fulfill({
        json: {
          total_open: byCategoryList.reduce((sum, c) => sum + c.open, 0),
          total_resolved: byCategoryList.reduce(
            (sum, c) => sum + c.resolved,
            0,
          ),
          critical_open: byCategoryList.reduce(
            (sum, c) => sum + c.critical_open,
            0,
          ),
          by_category: byCategoryList,
          by_repo: byRepoList,
        },
      })
      return
    }
    if (url.match(/\/findings\/[0-9a-f-]{36}$/)) {
      const id = url.split("/").pop()
      const issue = issues.find((i) => i.id === id) ?? issues[0]
      route.fulfill({ json: issue })
    } else {
      route.fulfill({ json: issues })
    }
  })
}

export async function mockFixes(
  page: Page,
  fixes = [MOCK_FIX_READY, MOCK_FIX_DELIVERED],
  pullRequests: unknown[] = [],
) {
  // Two globs, because the workflow engine's fix surface is addressed two ways:
  // by fix (`/workflow/fixes/...`) and by repository
  // (`/workflow/repositories/{id}/fixes|deliveries|pull-requests`). One glob
  // over `/workflow/**` would be simpler but would also swallow the scan and
  // finding routes, which have their own handlers.
  const handler = (route: Route) => {
    const url = route.request().url()
    const method = route.request().method()
    if (method === "POST" && url.includes("/pull-requests/sync")) {
      route.fulfill({ json: { synced: 0, updated: 0, relinked: 0 } })
    } else if (method === "POST" && url.includes("/regenerate")) {
      route.fulfill({ status: 202, json: { status: "queued" } })
    } else if (method === "POST" && url.includes("/retry")) {
      route.fulfill({ status: 202, json: { status: "queued" } })
    } else if (method === "POST" && url.includes("/deliveries")) {
      route.fulfill({ json: { status: "delivering" } })
    } else if (method === "POST" && url.endsWith("/fixes")) {
      // Repo-wide generation: `POST /workflow/repositories/{id}/fixes`.
      route.fulfill({ status: 202, json: { status: "queued", queued: 1 } })
    } else if (method === "DELETE") {
      route.fulfill({ status: 204 })
    } else if (url.includes("/pull-requests")) {
      route.fulfill({ json: pullRequests })
    } else if (url.match(/\/fixes\/[0-9a-f-]{36}$/)) {
      const id = url.split("/").pop()
      const fix = fixes.find((f) => f.id === id) ?? fixes[0]
      route.fulfill({ json: fix })
    } else {
      route.fulfill({ json: fixes })
    }
  }
  await page.route("**/api/v1/workflow/fixes**", handler)
  await page.route("**/api/v1/workflow/repositories/**", handler)
}

export async function mockRules(
  page: Page,
  rules = [MOCK_RULE_SECURITY, MOCK_RULE_RELIABILITY, MOCK_RULE_DISABLED],
) {
  await page.route("**/api/v1/rules**", (route) => {
    const url = route.request().url()
    const method = route.request().method()
    if (method === "PATCH") {
      route.fulfill({ json: { ...rules[0], enabled: !rules[0].enabled } })
    } else if (url.match(/\/rules\/[0-9a-f-]{36}$/)) {
      const id = url.split("/").pop()
      const rule = rules.find((r) => r.id === id) ?? rules[0]
      route.fulfill({ json: rule })
    } else {
      route.fulfill({ json: rules })
    }
  })
}

export async function mockBilling(
  page: Page,
  subscription = MOCK_SUBSCRIPTION,
  limits = MOCK_TIER_LIMITS,
  usage = MOCK_USAGE,
  { plans = MOCK_PLANS, invoices = [] as unknown[] } = {},
) {
  await page.route("**/api/v1/billing**", (route) => {
    const url = route.request().url()
    // Longest-prefix-ish ordering: /oss-applications must be tested before
    // /oss-application, and /subscription is the fallback.
    if (url.includes("/limits")) {
      route.fulfill({ json: limits })
    } else if (url.includes("/usage")) {
      route.fulfill({ json: usage })
    } else if (url.includes("/plans")) {
      route.fulfill({ json: plans })
    } else if (url.includes("/invoices")) {
      route.fulfill({ json: invoices })
    } else if (url.includes("/oss-application")) {
      route.fulfill({ json: [] })
    } else if (url.includes("/checkout") || url.includes("/portal")) {
      route.fulfill({ json: { url: "https://checkout.stripe.com/c/pay/test" } })
    } else {
      route.fulfill({ json: subscription })
    }
  })
}

export async function mockOrganizations(
  page: Page,
  orgs = [MOCK_ORG],
  aiProviders = MOCK_AI_PROVIDERS,
) {
  await page.route("**/api/v1/organizations**", (route) => {
    const url = route.request().url()
    if (url.includes("/ai-providers")) {
      route.fulfill({ json: aiProviders })
    } else if (route.request().method() === "PATCH") {
      route.fulfill({ json: orgs[0] })
    } else {
      route.fulfill({ json: orgs })
    }
  })
}

export async function mockInstallations(
  page: Page,
  installations = [MOCK_INSTALLATION],
) {
  await page.route("**/api/v1/installations**", (route) => {
    route.fulfill({ json: installations })
  })
}

export async function mockDockerTargets(
  page: Page,
  targets: Array<{ id: string; repo_id: string }> = [
    MOCK_DOCKER_TARGET,
    MOCK_DOCKER_TARGET_API,
  ],
  {
    files = [MOCK_DOCKER_FILE],
    findings = [MOCK_DOCKER_FINDING],
    fixes = [MOCK_DOCKER_FIX],
    scans = [MOCK_DOCKER_SCAN, MOCK_DOCKER_SCAN_FAILED],
    runtime = [MOCK_DOCKER_RUNTIME_BUILD],
    runtimeFixQueued = 1,
  } = {},
) {
  await page.route("**/api/v1/docker/targets**", (route) => {
    const url = route.request().url()
    const method = route.request().method()
    if (method === "DELETE") {
      route.fulfill({ status: 204 })
    } else if (method === "PATCH") {
      route.fulfill({ json: { id: targets[0].id, enabled: false } })
    } else if (method === "POST" && url.includes("/scan")) {
      route.fulfill({
        status: 202,
        json: { status: "queued", docker_target_id: targets[0].id },
      })
      // Before the generic /fixes branches: "/runtime-fixes" contains "/fixes",
      // so the broader check would swallow it.
    } else if (method === "POST" && url.includes("/runtime-fixes")) {
      route.fulfill({
        status: 202,
        json: {
          status: runtimeFixQueued ? "queued" : "no_dockerfile_path",
          queued: runtimeFixQueued,
        },
      })
    } else if (url.includes("/runtime")) {
      // Only the scanned target has measured builds, mirroring /scans.
      route.fulfill({ json: url.includes(targets[0].id) ? runtime : [] })
    } else if (method === "POST" && url.includes("/fixes")) {
      route.fulfill({ status: 202, json: { status: "queued", queued: 1 } })
    } else if (method === "POST" && url.includes("/deliver")) {
      route.fulfill({ status: 202, json: { status: "queued" } })
    } else if (url.includes("/files")) {
      route.fulfill({ json: files })
    } else if (url.includes("/findings")) {
      route.fulfill({ json: findings })
    } else if (url.includes("/fixes")) {
      route.fulfill({ json: fixes })
    } else if (url.includes("/scans")) {
      // Only the target that has actually been scanned has a history.
      const scanned = url.includes(targets[0].id) ? scans : []
      route.fulfill({ json: scanned })
    } else {
      // Both the org-wide list (no repo_id) and the per-repo list land here.
      const repoId = new URL(url).searchParams.get("repo_id")
      route.fulfill({
        json: repoId ? targets.filter((t) => t.repo_id === repoId) : targets,
      })
    }
  })
}

export async function mockAnsibleProjects(
  page: Page,
  projects: Array<{ id: string; repo_id: string }> = [
    MOCK_ANSIBLE_PROJECT,
    MOCK_ANSIBLE_PROJECT_ROLES,
  ],
  {
    files = [MOCK_ANSIBLE_FILE],
    findings = [MOCK_ANSIBLE_FINDING, MOCK_ANSIBLE_FINDING_FILE_LEVEL],
    fixes = [MOCK_ANSIBLE_FIX],
    scans = [MOCK_ANSIBLE_SCAN],
  } = {},
) {
  await page.route("**/api/v1/ansible-projects/**", (route) => {
    const url = route.request().url()
    const method = route.request().method()
    if (method === "DELETE") {
      route.fulfill({ status: 204 })
    } else if (method === "PATCH" && url.includes("/toggle")) {
      route.fulfill({
        json: { ansible_project_id: projects[0].id, enabled: false },
      })
    } else if (method === "POST" && url.includes("/scan")) {
      route.fulfill({
        status: 202,
        json: { status: "queued", ansible_project_id: projects[0].id },
      })
    } else if (method === "POST" && url.includes("/fixes")) {
      route.fulfill({ status: 202, json: { status: "queued", queued: 1 } })
    } else if (method === "POST" && url.includes("/deliver")) {
      route.fulfill({
        status: 202,
        json: {
          status: "queued",
          ansible_project_id: projects[0].id,
          pr_branch: `greensecops/ansible-${projects[0].id.slice(0, 8)}`,
        },
      })
    } else if (url.includes("/files")) {
      route.fulfill({ json: files })
    } else if (url.includes("/findings")) {
      route.fulfill({ json: findings })
    } else if (url.includes("/fixes")) {
      route.fulfill({ json: fixes })
    } else if (url.includes("/scans")) {
      // Only the project that has actually been scanned has a history.
      route.fulfill({ json: url.includes(projects[0].id) ? scans : [] })
    } else {
      // Both the org-wide list (no repo_id) and the per-repo list land here.
      const repoId = new URL(url).searchParams.get("repo_id")
      route.fulfill({
        json: repoId ? projects.filter((p) => p.repo_id === repoId) : projects,
      })
    }
  })
}

export async function mockEvents(page: Page) {
  await page.route("**/api/v1/events**", (route) => {
    route.fulfill({
      status: 200,
      headers: { "Content-Type": "text/event-stream" },
      body: ": keepalive\n\n",
    })
  })
}

// ─── Cross-engine dashboard overview ─────────────────────────────────────────

const SEVERITIES = ["critical", "high", "medium", "low", "info"] as const
const GRADE_LADDER = ["A+++", "A++", "A+", "A", "B", "C", "D", "F"] as const

type EngineOverrides = {
  open?: number
  critical?: number
  resolved?: number
  scanned?: number
  total?: number
  score?: number | null
  grade?: string | null
  fixes?: Record<string, number> | null
  topRules?: number
}

/**
 * One engine's block of `/overview/` stats.
 *
 * Built rather than hand-written per engine so the invariants the real backend
 * guarantees hold in the fixtures too: `by_severity` and `by_category` each sum
 * to `open`, and the fix buckets partition it. A fixture that broke those would
 * let a component bug through.
 */
function buildEngine(
  engine: Engine,
  section: OverviewSection,
  label: string,
  o: EngineOverrides = {},
) {
  const open = o.open ?? 0
  const critical = Math.min(o.critical ?? 0, open)
  const total = o.total ?? 0
  const scanned = o.scanned ?? total
  // Everything non-critical lands on "high" so the counts stay easy to assert.
  const bySeverity = SEVERITIES.map((severity) => ({
    severity,
    open:
      severity === "critical"
        ? critical
        : severity === "high"
          ? open - critical
          : 0,
    resolved: severity === "high" ? (o.resolved ?? 0) : 0,
  }))
  const byCategory = [
    "energy",
    "reliability",
    "security",
    "performance",
    "maintainability",
  ].map((category, i) => ({
    category,
    // All the open findings sit on "security" so the heatmap has one hot cell.
    open: category === "security" ? open : 0,
    resolved: i === 0 ? (o.resolved ?? 0) : 0,
    critical_open: category === "security" ? critical : 0,
  }))
  const fixes =
    o.fixes === null
      ? null
      : {
          unfixed: open,
          in_progress: 0,
          ready: 0,
          delivered: 0,
          landed: 0,
          failed: 0,
          ...(o.fixes ?? {}),
        }
  if (fixes) {
    const addressed =
      fixes.in_progress +
      fixes.ready +
      fixes.delivered +
      fixes.landed +
      fixes.failed
    fixes.unfixed = Math.max(open - addressed, 0)
  }
  return {
    engine,
    section,
    label,
    coverage: {
      total,
      enabled: total,
      scanned,
      never_scanned: total - scanned,
      latest_scan_failed: 0,
    },
    freshness: {
      last_completed_scan_at: scanned > 0 ? "2025-01-15T10:00:00Z" : null,
      last_scan_at: scanned > 0 ? "2025-01-15T10:00:00Z" : null,
    },
    score: {
      avg_score: o.score === undefined ? (scanned > 0 ? 72 : null) : o.score,
      grade: o.grade === undefined ? (scanned > 0 ? "B" : null) : o.grade,
      scored_targets: scanned,
      by_grade: GRADE_LADDER.map((grade) => ({
        grade,
        count: grade === "B" ? scanned : 0,
      })),
    },
    findings: {
      open,
      resolved: o.resolved ?? 0,
      critical_open: critical,
      by_severity: bySeverity,
      by_category: byCategory,
    },
    fixes,
    top_rules: Array.from(
      { length: o.topRules ?? (open > 0 ? 1 : 0) },
      (_, i) => ({
        rule_id: `00000000-0000-0000-0000-00000000000${i + 1}`,
        slug: `${engine}_rule_${i + 1}`,
        title: `${label} rule ${i + 1}`,
        severity: "high",
        category: "security",
        open: Math.max(open - i, 1),
      }),
    ),
  }
}

export function buildOverview(
  overrides: Partial<
    Record<Exclude<Engine, "telemetry">, EngineOverrides>
  > = {},
) {
  const engines = [
    buildEngine("workflow", "ci", "CI workflows", overrides.workflow),
    buildEngine("docker", "docker", "Docker", overrides.docker),
    buildEngine("terraform", "infra", "Terraform", overrides.terraform),
    // Cloud posture has no fix pipeline at all — `fixes` is null, never zeroes.
    buildEngine("cloud", "infra", "Cloud posture", {
      ...overrides.cloud,
      fixes: null,
    }),
  ]
  const sum = (pick: (e: (typeof engines)[number]) => number) =>
    engines.reduce((total, e) => total + pick(e), 0)
  const scored = engines.filter((e) => e.score.avg_score != null)
  const avg =
    scored.length > 0
      ? scored.reduce((t, e) => t + (e.score.avg_score ?? 0), 0) / scored.length
      : null
  return {
    generated_at: "2025-01-15T12:00:00Z",
    totals: {
      targets: sum((e) => e.coverage.total),
      enabled_targets: sum((e) => e.coverage.enabled),
      never_scanned_targets: sum((e) => e.coverage.never_scanned),
      open_findings: sum((e) => e.findings.open),
      resolved_findings: sum((e) => e.findings.resolved),
      critical_open: sum((e) => e.findings.critical_open),
      avg_score: avg,
      grade: avg != null ? "B" : null,
      by_severity: SEVERITIES.map((severity) => ({
        severity,
        open: sum(
          (e) =>
            e.findings.by_severity.find((s) => s.severity === severity)?.open ??
            0,
        ),
        resolved: sum(
          (e) =>
            e.findings.by_severity.find((s) => s.severity === severity)
              ?.resolved ?? 0,
        ),
      })),
      by_category: [
        "energy",
        "reliability",
        "security",
        "performance",
        "maintainability",
      ].map((category) => ({
        category,
        open: sum(
          (e) =>
            e.findings.by_category.find((c) => c.category === category)?.open ??
            0,
        ),
        resolved: sum(
          (e) =>
            e.findings.by_category.find((c) => c.category === category)
              ?.resolved ?? 0,
        ),
        critical_open: sum(
          (e) =>
            e.findings.by_category.find((c) => c.category === category)
              ?.critical_open ?? 0,
        ),
      })),
      engines_with_data: engines.filter((e) => e.coverage.total > 0).length,
    },
    engines,
  }
}

export const MOCK_OVERVIEW = buildOverview({
  workflow: {
    open: 3,
    critical: 1,
    resolved: 2,
    total: 2,
    scanned: 2,
    topRules: 2,
  },
  docker: { open: 2, critical: 0, total: 1, scanned: 1 },
  terraform: { open: 0, total: 1, scanned: 0, score: null, grade: null },
  cloud: { open: 1, critical: 1, total: 1, scanned: 1 },
})

export async function mockOverview(
  page: Page,
  overview: unknown = MOCK_OVERVIEW,
) {
  await page.route("**/api/v1/overview**", (route) => {
    route.fulfill({ json: overview })
  })
}
