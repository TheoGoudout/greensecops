// GreenSecOps API services — uses the same request infrastructure as the generated client
import { OpenAPI } from "@/client/core/OpenAPI"
import { request as __request } from "@/client/core/request"
import type {
  AnalysisPublic,
  BillingSubscriptionPublic,
  FixPublic,
  IssueCategory,
  IssuePublic,
  IssueSeverity,
  RepositoryPublic,
  RulePublic,
  TierLimits,
} from "./types"

export function listRepositories(params?: {
  orgId?: string
  enabled?: boolean
  skip?: number
  limit?: number
}) {
  return __request<RepositoryPublic[]>(OpenAPI, {
    method: "GET",
    url: "/api/v1/repositories/",
    query: {
      org_id: params?.orgId,
      enabled: params?.enabled,
      skip: params?.skip ?? 0,
      limit: params?.limit ?? 50,
    },
  })
}

export function getRepository(repoId: string) {
  return __request<RepositoryPublic>(OpenAPI, {
    method: "GET",
    url: "/api/v1/repositories/{repo_id}",
    path: { repo_id: repoId },
  })
}

export function toggleRepository(repoId: string, enabled: boolean) {
  return __request<{ repo_id: string; enabled: boolean }>(OpenAPI, {
    method: "PATCH",
    url: "/api/v1/repositories/{repo_id}/toggle",
    path: { repo_id: repoId },
    query: { enabled },
  })
}

export function listAnalyses(params?: {
  repoId?: string
  branch?: string
  grade?: string
  status?: string
  skip?: number
  limit?: number
}) {
  return __request<AnalysisPublic[]>(OpenAPI, {
    method: "GET",
    url: "/api/v1/analyses/",
    query: {
      repo_id: params?.repoId,
      branch: params?.branch,
      grade: params?.grade,
      status: params?.status,
      skip: params?.skip ?? 0,
      limit: params?.limit ?? 50,
    },
  })
}

export function getAnalysis(analysisId: string) {
  return __request<AnalysisPublic>(OpenAPI, {
    method: "GET",
    url: "/api/v1/analyses/{analysis_id}",
    path: { analysis_id: analysisId },
  })
}

export function triggerAnalysis(repoId: string, branch?: string) {
  return __request<{ status: string; repo_id: string }>(OpenAPI, {
    method: "POST",
    url: "/api/v1/analyses/trigger/{repo_id}",
    path: { repo_id: repoId },
    query: { branch },
  })
}

export function listIssues(params?: {
  analysisId?: string
  category?: IssueCategory
  severity?: IssueSeverity
  skip?: number
  limit?: number
}) {
  return __request<IssuePublic[]>(OpenAPI, {
    method: "GET",
    url: "/api/v1/issues/",
    query: {
      analysis_id: params?.analysisId,
      category: params?.category,
      severity: params?.severity,
      skip: params?.skip ?? 0,
      limit: params?.limit ?? 100,
    },
  })
}

export function listRules(params?: {
  category?: IssueCategory
  enabled?: boolean
  skip?: number
  limit?: number
}) {
  return __request<RulePublic[]>(OpenAPI, {
    method: "GET",
    url: "/api/v1/rules/",
    query: {
      category: params?.category,
      enabled: params?.enabled,
      skip: params?.skip ?? 0,
      limit: params?.limit ?? 100,
    },
  })
}

export function toggleRule(ruleId: string, enabled: boolean) {
  return __request<RulePublic>(OpenAPI, {
    method: "PATCH",
    url: "/api/v1/rules/{rule_id}/toggle",
    path: { rule_id: ruleId },
    query: { enabled },
  })
}

export function listFixes(params?: {
  issueId?: string
  status?: string
  skip?: number
  limit?: number
}) {
  return __request<FixPublic[]>(OpenAPI, {
    method: "GET",
    url: "/api/v1/fixes/",
    query: {
      issue_id: params?.issueId,
      status: params?.status,
      skip: params?.skip ?? 0,
      limit: params?.limit ?? 50,
    },
  })
}

export function generateFix(issueId: string) {
  return __request<{ status: string; issue_id: string }>(OpenAPI, {
    method: "POST",
    url: "/api/v1/fixes/generate/{issue_id}",
    path: { issue_id: issueId },
  })
}

export function getSubscription() {
  return __request<BillingSubscriptionPublic>(OpenAPI, {
    method: "GET",
    url: "/api/v1/billing/subscription",
  })
}

export function getLimits() {
  return __request<TierLimits>(OpenAPI, {
    method: "GET",
    url: "/api/v1/billing/limits",
  })
}
