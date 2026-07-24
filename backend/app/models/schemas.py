import uuid
from datetime import datetime
from typing import Any

from sqlmodel import Field, SQLModel

from .db import UserBase
from .enums import (
    AnalysisStatus,
    AnalysisTrigger,
    CIStatus,
    DynamicAnalysisStatus,
    FindingResolutionReason,
    FindingStatus,
    FixDeliveryMode,
    FixStatus,
    IssueCategory,
    IssueResolutionReason,
    IssueSeverity,
    IssueStatus,
    LLMProvider,
    PullRequestState,
    ReviewDecision,
    ScanStatus,
    TelemetryPhase,
    UserTier,
)


class UserPublic(UserBase):
    id: uuid.UUID
    github_username: str | None = None
    tier: UserTier = UserTier.free
    created_at: datetime | None = None


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


class OrganizationPublic(SQLModel):
    id: uuid.UUID
    name: str
    tier: UserTier
    default_llm_provider: LLMProvider | None = None
    default_llm_model: str | None = None
    fix_delivery_mode: FixDeliveryMode
    created_at: datetime | None = None


class OrganizationAIUpdate(SQLModel):
    default_llm_provider: LLMProvider | None = None
    default_llm_model: str | None = None


class AIProviderInfo(SQLModel):
    id: str
    name: str
    available: bool
    default_model: str
    models: list[str]


class AIProvidersPublic(SQLModel):
    providers: list[AIProviderInfo]


class RepositoryPublic(SQLModel):
    id: uuid.UUID
    full_name: str
    enabled: bool
    is_accessible: bool = True
    is_external: bool = False
    is_private: bool = False
    default_branch: str
    auto_fix_enabled: bool = False
    tier: UserTier | None = None
    # HMAC signature for the badge on the repo's default branch. Only set for
    # private repos (whose badge URLs must be signed); ``None`` for public
    # repos, which use plain badge URLs. The frontend appends it as ``?sig=``.
    badge_sig: str | None = None
    created_at: datetime | None = None
    avg_score: float | None = None
    grade: str | None = None


class ExternalRepositoryCreate(SQLModel):
    full_name: str = Field(max_length=512)
    installation_id: int | None = None


class AnalysisPublic(SQLModel):
    id: uuid.UUID
    repo_id: uuid.UUID
    workflow_file_id: uuid.UUID | None = None
    workflow_file_path: str | None = None
    repo_full_name: str | None = None
    content_hash: str
    status: AnalysisStatus
    score: float | None = None
    grade: str | None = None
    triggered_by: AnalysisTrigger
    branch: str | None = None
    commit_sha: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None


class IssuePublic(SQLModel):
    id: uuid.UUID
    analysis_id: uuid.UUID
    rule_id: uuid.UUID
    rule_slug: str
    severity: IssueSeverity
    category: IssueCategory
    line_start: int | None = None
    line_end: int | None = None
    message: str
    context: str | None = None
    status: IssueStatus
    created_at: datetime | None = None
    resolved_at: datetime | None = None
    resolution_reason: IssueResolutionReason | None = None
    needs_manual_work: bool = False
    manual_work_note: str | None = None
    fix_id: uuid.UUID | None = None
    fix_status: FixStatus | None = None
    workflow_file_path: str | None = None


class IssueCategoryStat(SQLModel):
    category: IssueCategory
    open: int
    resolved: int
    critical_open: int


class RepoCategoryStat(SQLModel):
    """A repo's open-issue counts and severity-weighted grade for one category.

    ``score``/``grade`` are ``None`` when the repo has no overall grade yet
    (e.g. no completed analysis). See ``RepoIssueStats`` for how categories
    are grouped per repo.
    """

    category: IssueCategory
    open: int
    critical_open: int
    score: float | None = None
    grade: str | None = None


class RepoIssueStats(SQLModel):
    """Per-repo issue breakdown — powers the dashboard's category health star
    diagram. Only populated on the unscoped (all-repos) stats call;
    meaningless once already filtered to a single ``repo_id``.

    ``score``/``grade`` here are the repo's own overall grade (same values as
    ``RepositoryPublic.avg_score``/``grade``), repeated so the frontend
    doesn't need a second lookup to size the radar's "no issues" fallback.
    Each entry in ``categories`` covers every ``IssueCategory``, including
    categories with zero open issues, so their scores average out to exactly
    the repo's overall score (see ``compute_category_scores``).
    """

    repo_id: uuid.UUID
    score: float | None = None
    grade: str | None = None
    categories: list[RepoCategoryStat] = []


class IssueStatsPublic(SQLModel):
    """Exact issue counts, computed by SQL aggregation rather than fetched and
    counted client-side — unaffected by any page's ``skip``/``limit``."""

    total_open: int
    total_resolved: int
    critical_open: int
    by_category: list[IssueCategoryStat]
    by_repo: list[RepoIssueStats] = []


class FixIssueSummary(SQLModel):
    id: uuid.UUID
    rule_slug: str | None = None
    severity: IssueSeverity | None = None
    category: IssueCategory | None = None
    message: str | None = None
    line_start: int | None = None
    line_end: int | None = None


class FixPublic(SQLModel):
    id: uuid.UUID
    workflow_file_id: uuid.UUID
    workflow_file_path: str | None = None
    repo_id: uuid.UUID | None = None
    pr_id: uuid.UUID | None = None
    llm_provider: LLMProvider
    llm_model: str
    status: FixStatus
    full_content: str | None = None
    base_content: str | None = None
    error_message: str | None = None
    pr_url: str | None = None
    pr_branch: str | None = None
    pr_state: PullRequestState | None = None
    comment_url: str | None = None
    created_at: datetime | None = None
    delivered_at: datetime | None = None
    issues: list[FixIssueSummary] = []


class WorkflowFilePublic(SQLModel):
    id: uuid.UUID
    path: str
    branch: str | None = None
    raw_content: str | None = None


class TerraformRootCreate(SQLModel):
    repo_id: uuid.UUID
    root_path: str = Field(max_length=512)


class TerraformRootPublic(SQLModel):
    id: uuid.UUID
    repo_id: uuid.UUID
    repo_full_name: str | None = None
    root_path: str
    enabled: bool
    last_scanned_at: datetime | None = None
    last_scanned_head_sha: str | None = None
    # Populated from the root's latest scan, mirroring how RepositoryPublic
    # surfaces the workflow-engine's grade — a root's grade IS its latest
    # scan's grade, there's no separate aggregation.
    latest_score: float | None = None
    latest_grade: str | None = None
    # HMAC signature for this root's badge, mirroring RepositoryPublic.badge_sig
    # — only set when the owning repo is private (public repos get plain,
    # unsigned badge URLs). The frontend appends it as ``?sig=``.
    badge_sig: str | None = None


class TerraformScanPublic(SQLModel):
    id: uuid.UUID
    terraform_root_id: uuid.UUID
    status: ScanStatus
    triggered_by: AnalysisTrigger
    branch: str | None = None
    commit_sha: str | None = None
    score: float | None = None
    grade: str | None = None
    error_message: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None


class TerraformFindingPublic(SQLModel):
    id: uuid.UUID
    scan_id: uuid.UUID
    terraform_root_id: uuid.UUID
    rule_id: uuid.UUID
    rule_slug: str
    resource_address: str | None = None
    file_path: str
    severity: IssueSeverity
    category: IssueCategory
    message: str
    context: str | None = None
    status: FindingStatus
    created_at: datetime | None = None
    resolved_at: datetime | None = None
    resolution_reason: FindingResolutionReason | None = None


class PullRequestPublic(SQLModel):
    id: uuid.UUID
    repo_id: uuid.UUID
    pr_branch: str
    pr_url: str | None = None
    pr_state: PullRequestState | None = None
    ci_status: CIStatus | None = None
    review_decision: ReviewDecision | None = None
    mergeable_state: str | None = None
    externally_modified: bool = False
    comment_url: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RulePublic(SQLModel):
    id: uuid.UUID
    slug: str
    category: IssueCategory
    severity: IssueSeverity
    title: str
    description: str
    enabled: bool


class DynamicEnrichmentPublic(SQLModel):
    """A runtime-telemetry finding, exposed for the frontend.

    Deliberately thinner than ``IssuePublic``: enrichments carry no severity,
    category, status/lifecycle, line numbers, or fix linkage, so they are
    presented as their own "Runtime findings" class rather than merged into the
    static issue list.
    """

    id: uuid.UUID
    telemetry_run_id: uuid.UUID
    workflow_run_id: int | None = None
    rule_slug: str
    evidence: str
    recommendation: str
    created_at: datetime | None = None


class TelemetryRunPublic(SQLModel):
    id: uuid.UUID
    workflow_run_id: int
    phase: TelemetryPhase | None = None
    dynamic_status: DynamicAnalysisStatus | None = None
    runner_specs: dict[str, Any] = {}
    metrics: dict[str, Any] = {}
    collected_at: datetime | None = None
    enrichments: list[DynamicEnrichmentPublic] = []


class TelemetryAveragePublic(SQLModel):
    """Averaged telemetry across a repo's runs.

    Sample-derived fields are averaged over ``TelemetryMetricSample`` rows;
    run-derived fields (``avg_ram_percent``, ``avg_vcpus``) come from the
    per-run ``metrics``/``runner_specs`` JSON. Any field is ``None`` when no
    data supports it.
    """

    run_count: int = 0
    sample_count: int = 0
    avg_cpu_percent: float | None = None
    avg_ram_used_mb: float | None = None
    avg_ram_percent: float | None = None
    avg_disk_used_gb: float | None = None
    avg_net_bytes_sent: float | None = None
    avg_net_bytes_recv: float | None = None
    avg_vcpus: float | None = None


class TelemetrySummaryPublic(SQLModel):
    average: TelemetryAveragePublic
    runs: list[TelemetryRunPublic] = []


class BillingSubscriptionPublic(SQLModel):
    id: uuid.UUID
    tier: UserTier
    analyses_used: int
    fixes_used: int
    repos_used: int = 0
    period_start: datetime | None = None
    period_end: datetime | None = None


class Message(SQLModel):
    message: str


class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


class TokenPayload(SQLModel):
    sub: str | None = None


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)
