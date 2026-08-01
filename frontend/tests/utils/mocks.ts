import type { Page } from "@playwright/test"
import type { RepositoryPublic, UserPublic } from "@/client"
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
}

export const MOCK_WORKFLOW_FILE_DEPLOY = {
  id: ID.workflowFileDeploy,
  path: ".github/workflows/deploy.yml",
  branch: "main",
  raw_content: WORKFLOW_RAW_CONTENT,
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
  workflow_file_path: ".github/workflows/ci.yml",
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
  workflow_file_path: ".github/workflows/ci.yml",
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
  workflow_file_path: ".github/workflows/ci.yml",
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
  workflow_file_path: ".github/workflows/ci.yml",
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
  workflow_file_path: ".github/workflows/ci.yml",
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
  workflow_file_path: ".github/workflows/ci.yml",
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
  workflow_file_path: ".github/workflows/ci.yml",
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
  workflow_file_path: ".github/workflows/ci.yml",
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
  workflow_file_path: ".github/workflows/ci.yml",
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
  workflow_file_path: ".github/workflows/ci.yml",
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
  workflow_file_path: ".github/workflows/deploy.yml",
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
  workflow_file_path: ".github/workflows/release.yml",
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
  workflow_file_path: ".github/workflows/ci.yml",
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
  workflow_file_path: ".github/workflows/ci.yml",
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
  workflow_file_path: ".github/workflows/ci.yml",
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
export const MOCK_SUBSCRIPTION = {
  id: ID.subscription,
  tier: "free" as const,
  analyses_used: 12,
  fixes_used: 2,
  repos_used: 1,
  period_start: null,
  period_end: null,
}

export const MOCK_TIER_LIMITS = {
  tier: "free",
  limits: { analyses: 50, fixes: 5, repos: 3 },
}

export const MOCK_SUBSCRIPTION_PRO = {
  id: ID.subscriptionPro,
  tier: "pro" as const,
  analyses_used: 5,
  fixes_used: 10,
  repos_used: 2,
  period_start: "2024-01-01T00:00:00Z",
  period_end: "2024-02-01T00:00:00Z",
}

export const MOCK_TIER_LIMITS_PRO = {
  tier: "pro",
  limits: { analyses: 500, fixes: 100, repos: 20 },
}

export const MOCK_SUBSCRIPTION_AT_LIMIT = {
  id: ID.subscription,
  tier: "free" as const,
  analyses_used: 50,
  fixes_used: 5,
  repos_used: 3,
  period_start: null,
  period_end: null,
}

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
  await page.route("**/api/v1/repositories/**", (route) => {
    const url = route.request().url()
    if (url.includes("/workflow-files")) {
      route.fulfill({ json: [MOCK_WORKFLOW_FILE] })
    } else if (url.match(/\/repositories\/[0-9a-f-]{36}$/)) {
      const id = url.split("/").pop()
      const repo = repos.find((r) => r.id === id) ?? repos[0]
      route.fulfill({ json: repo })
    } else if (url.includes("/toggle")) {
      const repo = repos[0]
      route.fulfill({ json: { ...repo, enabled: !repo.enabled } })
    } else if (url.includes("/integrate-action")) {
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
  await page.route("**/api/v1/analyses/**", (route) => {
    const url = route.request().url()
    const method = route.request().method()
    if (method === "POST" && url.includes("/trigger/")) {
      route.fulfill({
        status: 202,
        json: { status: "queued", repo_id: MOCK_REPO.id },
      })
    } else if (url.match(/\/analyses\/[0-9a-f-]{36}$/)) {
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
  await page.route("**/api/v1/issues/**", (route) => {
    const url = route.request().url()
    if (url.includes("/issues/stats")) {
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
    if (url.match(/\/issues\/[0-9a-f-]{36}$/)) {
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
  await page.route("**/api/v1/fixes/**", (route) => {
    const url = route.request().url()
    const method = route.request().method()
    if (method === "POST" && url.includes("/sync-pr-status")) {
      route.fulfill({ json: { synced: 0, updated: 0, relinked: 0 } })
    } else if (method === "POST" && url.includes("/regenerate")) {
      route.fulfill({ status: 202, json: { status: "queued" } })
    } else if (method === "POST" && url.includes("/generate")) {
      route.fulfill({ status: 202, json: { status: "queued", queued: 1 } })
    } else if (method === "POST" && url.includes("/deliver")) {
      route.fulfill({ json: { status: "delivering" } })
    } else if (method === "DELETE") {
      route.fulfill({ status: 204 })
    } else if (url.includes("/pull-requests/")) {
      route.fulfill({ json: pullRequests })
    } else if (url.match(/\/fixes\/[0-9a-f-]{36}$/)) {
      const id = url.split("/").pop()
      const fix = fixes.find((f) => f.id === id) ?? fixes[0]
      route.fulfill({ json: fix })
    } else {
      route.fulfill({ json: fixes })
    }
  })
}

export async function mockRules(
  page: Page,
  rules = [MOCK_RULE_SECURITY, MOCK_RULE_RELIABILITY, MOCK_RULE_DISABLED],
) {
  await page.route("**/api/v1/rules/**", (route) => {
    const url = route.request().url()
    if (url.includes("/toggle")) {
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
) {
  await page.route("**/api/v1/billing/**", (route) => {
    const url = route.request().url()
    if (url.includes("/limits")) {
      route.fulfill({ json: limits })
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
  await page.route("**/api/v1/organizations/**", (route) => {
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
  await page.route("**/api/v1/installations/**", (route) => {
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
  } = {},
) {
  await page.route("**/api/v1/docker-targets/**", (route) => {
    const url = route.request().url()
    const method = route.request().method()
    if (method === "DELETE") {
      route.fulfill({ status: 204 })
    } else if (method === "PATCH" && url.includes("/toggle")) {
      route.fulfill({ json: { id: targets[0].id, enabled: false } })
    } else if (method === "POST" && url.includes("/scan")) {
      route.fulfill({
        status: 202,
        json: { status: "queued", docker_target_id: targets[0].id },
      })
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

export async function mockEvents(page: Page) {
  await page.route("**/api/v1/events/**", (route) => {
    route.fulfill({
      status: 200,
      headers: { "Content-Type": "text/event-stream" },
      body: ": keepalive\n\n",
    })
  })
}
