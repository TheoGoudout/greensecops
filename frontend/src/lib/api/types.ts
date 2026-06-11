// GreenSecOps domain types — mirrors backend app/models.py public schemas

export type UserTier = "free" | "starter" | "pro" | "ultimate" | "open_source"

export type AnalysisStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "skipped"

export type AnalysisTrigger =
  | "webhook_push"
  | "webhook_workflow_run"
  | "manual"
  | "scheduled"

export type IssueSeverity = "critical" | "high" | "medium" | "low" | "info"

export type IssueCategory =
  | "energy"
  | "reliability"
  | "security"
  | "performance"
  | "maintainability"

export type FixStatus =
  | "pending"
  | "generating"
  | "ready"
  | "delivering"
  | "delivered"
  | "failed"
  | "rejected"

export type LLMProvider = "openai" | "anthropic" | "gemini" | "ollama"

export type FixDeliveryMode = "pr" | "comment" | "disabled"

export interface RepositoryPublic {
  id: string
  full_name: string
  enabled: boolean
  default_branch: string
  tier: UserTier | null
  created_at: string | null
}

export interface AnalysisPublic {
  id: string
  repo_id: string
  workflow_file_id: string
  content_hash: string
  status: AnalysisStatus
  score: number | null
  grade: string | null
  triggered_by: AnalysisTrigger
  branch: string | null
  commit_sha: string | null
  created_at: string | null
  completed_at: string | null
}

export interface IssuePublic {
  id: string
  analysis_id: string
  rule_id: string
  severity: IssueSeverity
  category: IssueCategory
  line_start: number | null
  line_end: number | null
  message: string
  context: string | null
  created_at: string | null
}

export interface RulePublic {
  id: string
  slug: string
  category: IssueCategory
  severity: IssueSeverity
  title: string
  description: string
  enabled: boolean
}

export interface FixPublic {
  id: string
  issue_id: string
  llm_provider: LLMProvider
  llm_model: string
  status: FixStatus
  diff: string | null
  pr_url: string | null
  comment_url: string | null
  created_at: string | null
  delivered_at: string | null
}

export interface BillingSubscriptionPublic {
  id: string
  tier: UserTier
  analyses_used: number
  fixes_used: number
  period_start: string | null
  period_end: string | null
}

export interface TierLimits {
  tier: UserTier
  limits: {
    analyses: number | null
    fixes: number | null
    repos: number | null
  }
}
