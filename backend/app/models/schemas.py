import uuid
from datetime import datetime
from typing import Any

from sqlmodel import Field, SQLModel

from .db import UserBase
from .enums import (
    AnalysisStatus,
    AnalysisTrigger,
    CIStatus,
    CloudAccountStatus,
    CloudProvider,
    DynamicAnalysisStatus,
    FindingResolutionReason,
    FindingStatus,
    FixDeliveryMode,
    FixStatus,
    InvoiceStatus,
    IssueCategory,
    IssueResolutionReason,
    IssueSeverity,
    IssueStatus,
    LLMProvider,
    OssApplicationStatus,
    OverviewEngineKey,
    OverviewSection,
    PullRequestState,
    ReviewDecision,
    ScanStatus,
    SubscriptionStatus,
    TelemetryPhase,
    UsageEngine,
    UsageMeter,
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
    # The owning organization — lets the frontend scope org-level resources
    # (e.g. the repo's connected AWS cloud accounts) to this repo's org.
    org_id: uuid.UUID
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


# --------------------------------------------------------------------------
# Shared bases for the per-engine public schemas
# --------------------------------------------------------------------------
# The Terraform, Docker and cloud engines expose the same shape for a scan, a
# finding and a fix; only their locators differ. These bases are that shape
# written once. Pydantic flattens inherited fields, so the emitted OpenAPI
# schema for each concrete class is exactly what it was when every field was
# spelled out — the generated frontend/action clients are unaffected.


class ScanPublicBase(SQLModel):
    """One engine run, as the UI shows it in a scan history list."""

    id: uuid.UUID
    status: ScanStatus
    triggered_by: AnalysisTrigger
    score: float | None = None
    grade: str | None = None
    error_message: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None


class RepoScanPublicBase(ScanPublicBase):
    """A scan of code in a repository, which records where it ran."""

    branch: str | None = None
    commit_sha: str | None = None


class FindingPublicBase(SQLModel):
    """A rule violation with its lifecycle, minus the engine's own locators."""

    id: uuid.UUID
    scan_id: uuid.UUID
    rule_id: uuid.UUID
    rule_slug: str
    severity: IssueSeverity
    category: IssueCategory
    message: str
    context: str | None = None
    status: FindingStatus
    created_at: datetime | None = None
    resolved_at: datetime | None = None
    resolution_reason: FindingResolutionReason | None = None


class FixablePublicBase(FindingPublicBase):
    """A finding an engine can generate a fix for — mirrors
    ``IssuePublic.fix_id``/``fix_status``. Cloud findings have no fix pipeline,
    so they stay on the plain base."""

    fix_id: uuid.UUID | None = None
    fix_status: FixStatus | None = None


class FilePublicBase(SQLModel):
    """A file's live source, fetched from GitHub on demand.

    Terraform and Docker files aren't persisted the way ``WorkflowFile`` is, so
    these carry no id or branch — just the path and its content.
    """

    path: str
    raw_content: str


class FileFixPublicBase(SQLModel):
    """An LLM rewrite of one file and the PR it was delivered on."""

    id: uuid.UUID
    file_path: str
    pr_id: uuid.UUID | None = None
    llm_provider: LLMProvider
    llm_model: str
    status: FixStatus
    full_content: str | None = None
    error_message: str | None = None
    pr_url: str | None = None
    pr_branch: str | None = None
    pr_state: PullRequestState | None = None
    created_at: datetime | None = None
    delivered_at: datetime | None = None


class ScanTargetPublicBase(SQLModel):
    """A registered scan target, carrying the grade of its latest scan.

    A target's grade *is* its latest completed scan's grade; there is no
    separate aggregation to keep in sync. ``badge_sig`` mirrors
    ``RepositoryPublic.badge_sig`` — set only when the owning repo is private,
    since public repos get plain, unsigned badge URLs.
    """

    id: uuid.UUID
    repo_id: uuid.UUID
    repo_full_name: str | None = None
    root_path: str
    enabled: bool
    last_scanned_at: datetime | None = None
    last_scanned_head_sha: str | None = None
    latest_score: float | None = None
    latest_grade: str | None = None
    badge_sig: str | None = None


class DockerTargetCreate(SQLModel):
    repo_id: uuid.UUID
    # "" means the repository root, which is what installation sync creates
    # automatically. Explicit targets are for monorepos that want each
    # sub-project graded separately.
    root_path: str = Field(default="", max_length=512)


class DockerTargetPublic(ScanTargetPublicBase):
    pass


class DockerScanPublic(RepoScanPublicBase):
    docker_target_id: uuid.UUID
    # The score is a mean of per-file scores; this is its denominator, without
    # which a grade can't be reasoned about after the fact.
    file_count: int | None = None


class DockerFindingPublic(FixablePublicBase):
    docker_target_id: uuid.UUID
    file_path: str
    # Whichever locator the rule reports: a Compose rule names the service, a
    # Dockerfile rule the build stage. Both null for a file-level rule.
    service_name: str | None = None
    stage_name: str | None = None
    # 1-based line span of the offending instruction or service block, so the
    # frontend can annotate the finding inline on the source.
    line_start: int | None = None
    line_end: int | None = None


class DockerFixPublic(FileFixPublicBase):
    docker_target_id: uuid.UUID


class DockerRuntimeFindingPublic(SQLModel):
    """One ``DockerBuildEnrichment`` dressed for the Runtime tab.

    The stored row carries only a rule slug; severity, category and title are
    resolved from the rule catalog here so the tab can sort and colour without
    a second request. All three are nullable because a Rego rule shipped
    without a seed entry in ``core/db.py`` still evaluates and still produces
    enrichments — it just has no catalog row to describe it.
    """

    id: uuid.UUID
    telemetry_id: uuid.UUID
    rule_slug: str
    rule_title: str | None = None
    severity: IssueSeverity | None = None
    category: IssueCategory | None = None
    evidence: str
    recommendation: str
    created_at: datetime | None = None


class DockerBuildTelemetryPublic(SQLModel):
    """One measured build, with the findings its measurements produced.

    ``layers`` and ``containers`` are stored as JSON text (they are
    collector-shaped and never queried relationally) and decoded here, so the
    frontend never parses a string out of a typed field.
    """

    id: uuid.UUID
    workflow_run_id: int
    image_ref: str | None = None
    dockerfile_path: str | None = None
    image_size_bytes: int | None = None
    context_size_bytes: int | None = None
    build_duration_ms: int | None = None
    cache_hit_ratio: float | None = None
    layers: list[dict[str, Any]] = Field(default_factory=list)
    containers: list[dict[str, Any]] = Field(default_factory=list)
    collected_at: datetime | None = None
    findings: list[DockerRuntimeFindingPublic] = Field(default_factory=list)


class DockerFilePublic(FilePublicBase):
    """A Dockerfile or Compose file's live source for a target.

    Not persisted (mirroring ``TerraformFilePublic``): fetched from GitHub on
    demand, so it carries no id/branch — just path and content. ``kind`` lets
    the viewer pick a syntax highlighter without re-deriving it from the name.
    """

    kind: str


class TerraformRootCreate(SQLModel):
    repo_id: uuid.UUID
    root_path: str = Field(max_length=512)


class TerraformRootPublic(ScanTargetPublicBase):
    pass


class TerraformScanPublic(RepoScanPublicBase):
    terraform_root_id: uuid.UUID


class TerraformFindingPublic(FixablePublicBase):
    terraform_root_id: uuid.UUID
    resource_address: str | None = None
    file_path: str
    # 1-based line span of the offending block, when the scanner could locate
    # it — lets the frontend annotate the finding inline on the ``.tf`` source.
    line_start: int | None = None
    line_end: int | None = None
    # Directory-derived module locator + full Terraform address; null for
    # root-module resources. See ``hcl_parser.derive_module_path``.
    module_path: str | None = None
    terraform_address: str | None = None


class TerraformFilePublic(FilePublicBase):
    """A ``.tf`` file's live source for a Terraform root.

    Terraform files aren't persisted (unlike ``WorkflowFile``); they're fetched
    from GitHub on demand, so this carries no id/branch — just the path and
    content, mirroring the shape of ``WorkflowFilePublic``.
    """


class TerraformFixPublic(FileFixPublicBase):
    terraform_root_id: uuid.UUID


class CloudAccountCreate(SQLModel):
    org_id: uuid.UUID
    display_name: str = Field(max_length=255)
    role_arn: str = Field(max_length=512)
    regions: list[str] = Field(default_factory=list)


class CloudAccountPublic(SQLModel):
    id: uuid.UUID
    org_id: uuid.UUID
    provider: CloudProvider
    display_name: str
    role_arn: str | None = None
    external_id: str
    regions: list[str] = []
    status: CloudAccountStatus
    last_synced_at: datetime | None = None
    # Populated from the account's latest scan, mirroring TerraformRootPublic.
    latest_score: float | None = None
    latest_grade: str | None = None
    created_at: datetime | None = None


class CloudScanPublic(ScanPublicBase):
    cloud_account_id: uuid.UUID
    region: str | None = None
    resource_count: int = 0


class CloudFindingPublic(FindingPublicBase):
    cloud_account_id: uuid.UUID
    resource_type: str
    resource_id: str
    region: str | None = None


# The cross-engine dashboard overview. Everything below is an *aggregate* view
# of the shapes the bases above describe — no row of any of these is persisted.
# It lives here, after the last per-engine block, because it reuses
# ``IssueCategoryStat`` from the CI block and the engine enums from all four.


class SeverityStat(SQLModel):
    """Open/resolved finding counts for one severity.

    Emitted for every ``IssueSeverity`` including zeros, so the frontend can
    render a fixed-segment severity bar without gap logic.
    """

    severity: IssueSeverity
    open: int
    resolved: int


class GradeStat(SQLModel):
    """How many scan targets currently hold this grade.

    Emitted for every rung of ``services.scoring.GRADE_LADDER`` in order, best
    first, plus any grade found in the data that isn't on the ladder — grades
    are free-form ``VARCHAR(8)``, so a row written before a ladder change must
    still be counted rather than silently dropped.
    """

    grade: str
    count: int


class TopRuleStat(SQLModel):
    """A rule ranked by how many open findings it accounts for."""

    rule_id: uuid.UUID
    slug: str
    title: str
    severity: IssueSeverity
    category: IssueCategory
    open: int


class EngineCoverageStat(SQLModel):
    """How much of what could be scanned actually has been.

    ``enabled`` means different things per engine — a bool column for Docker
    and Terraform targets, ``CloudAccountStatus.connected`` for a cloud
    account. The CI engine's target is a ``WorkflowFile``, which has no enable
    switch at all, so there ``enabled == total``.
    """

    total: int
    enabled: int
    scanned: int
    never_scanned: int
    # Targets whose most recent scan of *any* status failed. Independent of
    # `scanned`: a target can hold a good grade from an older completed scan
    # and still have a failing latest run.
    latest_scan_failed: int


class EngineFreshnessStat(SQLModel):
    last_completed_scan_at: datetime | None
    last_scan_at: datetime | None


class EngineScoreStat(SQLModel):
    """Average of each target's latest *completed* scan score.

    A target whose latest scan failed keeps the score of its last good scan —
    the same rule ``api/mappers/base.latest_completed_scan`` applies per
    target, so a grade here always matches the one that engine's own list
    endpoint reports.
    """

    avg_score: float | None
    grade: str | None
    scored_targets: int
    by_grade: list[GradeStat]


class EngineFindingStat(SQLModel):
    open: int
    resolved: int
    critical_open: int
    by_severity: list[SeverityStat]
    by_category: list[IssueCategoryStat]


class EngineFixPipelineStat(SQLModel):
    """Open findings bucketed by the state of the fix addressing them.

    ``unfixed`` mirrors ``list_issues(unfixed=True)``: no fix row at all, or a
    fix in one of the rejected/superseded states. The buckets are disjoint and
    sum to ``EngineFindingStat.open``.
    """

    unfixed: int
    in_progress: int
    ready: int
    delivered: int
    landed: int
    failed: int


class EngineOverview(SQLModel):
    engine: OverviewEngineKey
    section: OverviewSection
    label: str
    coverage: EngineCoverageStat
    freshness: EngineFreshnessStat
    score: EngineScoreStat
    findings: EngineFindingStat
    # ``None`` for the cloud engine, which has no fix pipeline at all —
    # ``CloudFinding`` carries no ``fix_id``. An all-zero object would read as
    # "nothing left to fix" rather than "not a thing here".
    fixes: EngineFixPipelineStat | None
    top_rules: list[TopRuleStat]


class OverviewTotals(SQLModel):
    """All-engine roll-up for the dashboard's summary header.

    ``avg_score`` is the unweighted mean of the per-engine averages that
    exist, not of every target: averaging targets directly would let a repo
    with forty workflow files drown out a failing cloud posture.
    """

    targets: int
    enabled_targets: int
    never_scanned_targets: int
    open_findings: int
    resolved_findings: int
    critical_open: int
    avg_score: float | None
    grade: str | None
    by_severity: list[SeverityStat]
    by_category: list[IssueCategoryStat]
    engines_with_data: int


class OverviewPublic(SQLModel):
    generated_at: datetime
    totals: OverviewTotals
    # Always all four engines, zeroed where there is nothing to report, so the
    # dashboard can render a stable set of sections instead of appearing to
    # lose one when an org has no Terraform roots yet.
    engines: list[EngineOverview]


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
    """The billing page's headline: plan, payment state, and usage.

    ``tier`` is the purchased plan and ``effective_tier`` is what limits are
    actually being applied — they differ exactly when a subscription is
    ``unpaid`` or ``canceled``, and showing both is what lets the UI say "Pro,
    currently limited to Free" instead of silently misreporting one or other.
    """

    id: uuid.UUID
    tier: UserTier
    effective_tier: UserTier
    status: SubscriptionStatus
    analyses_used: int
    fixes_used: int
    repos_used: int = 0
    period_start: datetime | None = None
    period_end: datetime | None = None
    # Populated while ``past_due``: when full service stops if nothing is paid.
    grace_expires_at: datetime | None = None
    cancel_at_period_end: bool = False
    trial_end: datetime | None = None
    # False on deployments with no Stripe credentials, so the UI can hide the
    # upgrade and portal buttons instead of offering a 503.
    billing_enabled: bool = False


class PlanLimitsPublic(SQLModel):
    """``None`` means unlimited, at every layer up to the UI."""

    analyses: int | None = None
    fixes: int | None = None
    repos: int | None = None


class PlanPublic(SQLModel):
    tier: UserTier
    name: str
    price_cents: int
    price_display: str
    tagline: str
    limits: PlanLimitsPublic
    auto_fix: bool
    public_repos_only: bool
    is_purchasable: bool
    features: list[str] = []


class UsageBreakdownPublic(SQLModel):
    """How much of one meter a single engine accounted for this period."""

    meter: UsageMeter
    engine: UsageEngine
    quantity: int


class UsagePublic(SQLModel):
    """Per-meter usage with the engine split behind it.

    The breakdown is what answers "why am I at 90%" — before the ledger there
    was no way to tell a user that their Terraform roots, not their workflows,
    were spending the allowance.
    """

    period_start: datetime | None = None
    period_end: datetime | None = None
    analyses_used: int = 0
    fixes_used: int = 0
    repos_used: int = 0
    limits: PlanLimitsPublic
    breakdown: list[UsageBreakdownPublic] = []


class InvoicePublic(SQLModel):
    id: uuid.UUID
    stripe_invoice_id: str
    number: str | None = None
    status: InvoiceStatus
    amount_due_cents: int
    amount_paid_cents: int
    currency: str
    hosted_invoice_url: str | None = None
    invoice_pdf: str | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    paid_at: datetime | None = None
    created_at: datetime | None = None


class CheckoutRequest(SQLModel):
    tier: UserTier


class CheckoutSessionPublic(SQLModel):
    """The Stripe-hosted URL the browser must be sent to."""

    url: str


class OssApplicationCreate(SQLModel):
    repo_url: str = Field(min_length=1, max_length=512)
    license_name: str = Field(min_length=1, max_length=128)
    justification: str = Field(min_length=1, max_length=4096)


class OssApplicationReview(SQLModel):
    approve: bool
    review_note: str | None = Field(default=None, max_length=2048)


class OssApplicationPublic(SQLModel):
    id: uuid.UUID
    user_id: uuid.UUID
    repo_url: str
    license_name: str
    justification: str
    status: OssApplicationStatus
    review_note: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime | None = None


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
