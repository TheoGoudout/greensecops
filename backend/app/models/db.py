import uuid
from datetime import datetime, timezone
from typing import Optional

import sqlalchemy as sa
from pydantic import EmailStr
from sqlalchemy import DateTime, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from .enums import (
    AnalysisFailureKind,
    AnalysisStatus,
    AnalysisTrigger,
    CIStatus,
    DynamicAnalysisStatus,
    FixDeliveryMode,
    FixStatus,
    IssueCategory,
    IssueResolutionReason,
    IssueSeverity,
    IssueStatus,
    LLMProvider,
    OrgRole,
    PullRequestState,
    RepositoryStatus,
    ReviewDecision,
    TelemetryPhase,
    UserTier,
)


def get_datetime_utc() -> datetime:
    return datetime.now(timezone.utc)


# ─── User ────────────────────────────────────────────────────────────────────


class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    full_name: str | None = Field(default=None, max_length=255)


class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


class UserUpdate(UserBase):
    email: EmailStr | None = Field(default=None, max_length=255)  # type: ignore[assignment]
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    github_id: int | None = Field(default=None, unique=True, index=True)
    github_username: str | None = Field(default=None, max_length=255)
    tier: UserTier = Field(default=UserTier.free)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )
    org_memberships: list["OrgMember"] = Relationship(
        back_populates="user", cascade_delete=True
    )
    billing_subscription: Optional["BillingSubscription"] = Relationship(
        back_populates="user"
    )


# ─── Organization ────────────────────────────────────────────────────────────


class Organization(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    github_org_id: int | None = Field(default=None, unique=True, index=True)
    installation_id: int | None = Field(default=None, unique=True, index=True)
    name: str = Field(max_length=255, index=True)
    tier: UserTier = Field(default=UserTier.free)
    default_llm_provider: LLMProvider | None = Field(default=None)
    default_llm_model: str | None = Field(default=None, max_length=255)
    fix_delivery_mode: FixDeliveryMode = Field(default=FixDeliveryMode.pr)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    members: list["OrgMember"] = Relationship(
        back_populates="organization", cascade_delete=True
    )
    repositories: list["Repository"] = Relationship(
        back_populates="organization", cascade_delete=True
    )


class OrgMember(SQLModel, table=True):
    __tablename__ = "org_member"
    org_id: uuid.UUID = Field(
        foreign_key="organization.id", primary_key=True, ondelete="CASCADE"
    )
    user_id: uuid.UUID = Field(
        foreign_key="user.id", primary_key=True, ondelete="CASCADE"
    )
    role: OrgRole = Field(default=OrgRole.member)
    joined_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    organization: Organization | None = Relationship(back_populates="members")
    user: Optional["User"] = Relationship(back_populates="org_memberships")


# ─── Repository ──────────────────────────────────────────────────────────────


class Repository(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    org_id: uuid.UUID = Field(
        foreign_key="organization.id", nullable=False, ondelete="CASCADE"
    )
    github_repo_id: int = Field(unique=True, index=True)
    full_name: str = Field(max_length=512, index=True)
    installation_id: int | None = Field(default=None, index=True)
    enabled: bool = Field(default=False)
    is_accessible: bool = Field(default=True)
    is_external: bool = Field(default=False)
    # GitHub repo visibility, synced from the API. Drives badge-URL signing:
    # private repos require an HMAC-signed badge URL to serve a real grade,
    # public repos are served on plain URLs.
    is_private: bool = Field(
        default=False, sa_column_kwargs={"server_default": "false"}
    )
    # Accessibility / lifecycle axis, owned by the RepositoryMachine (migration
    # 0031). ``is_accessible`` is a machine-synced cache of ``status == active``;
    # ``enabled`` (user opt-in) stays an independent flag.
    status: RepositoryStatus = Field(
        default=RepositoryStatus.active,
        sa_column_kwargs={"server_default": RepositoryStatus.active.value},
    )
    default_branch: str = Field(default="main", max_length=255)
    # Polling cursors (external repos receive no webhooks): the default-branch
    # head last seen by the poller and when. A change in ``last_polled_head_sha``
    # is what triggers a polled analysis, the way a ``push`` webhook would.
    last_polled_head_sha: str | None = Field(default=None, max_length=40)
    last_polled_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)
    )
    fix_delivery_mode: FixDeliveryMode | None = Field(default=None)
    auto_fix_enabled: bool = Field(default=False)
    llm_provider: LLMProvider | None = Field(default=None)
    llm_model: str | None = Field(default=None, max_length=255)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    organization: Organization | None = Relationship(back_populates="repositories")
    workflow_files: list["WorkflowFile"] = Relationship(
        back_populates="repository", cascade_delete=True
    )
    analyses: list["Analysis"] = Relationship(
        back_populates="repository", cascade_delete=True
    )
    telemetry_runs: list["TelemetryRun"] = Relationship(
        back_populates="repository", cascade_delete=True
    )
    pull_requests: list["PullRequest"] = Relationship(
        back_populates="repository", cascade_delete=True
    )


# ─── WorkflowFile ─────────────────────────────────────────────────────────────


class WorkflowFile(SQLModel, table=True):
    __tablename__ = "workflow_file"
    __table_args__ = (
        UniqueConstraint(
            "repo_id", "branch", "path", name="uq_workflow_file_repo_branch_path"
        ),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    repo_id: uuid.UUID = Field(
        foreign_key="repository.id", nullable=False, ondelete="CASCADE"
    )
    # Workflow content is tracked per branch; issues hang off the per-branch
    # row, so reconciliation on one branch cannot touch another branch's state.
    branch: str = Field(default="main", max_length=255)
    path: str = Field(max_length=512)
    content_hash: str = Field(max_length=64, index=True)
    raw_content: str
    fetched_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    repository: Repository | None = Relationship(back_populates="workflow_files")
    analyses: list["Analysis"] = Relationship(
        back_populates="workflow_file",
    )
    fix: Optional["Fix"] = Relationship(back_populates="workflow_file")


# ─── Rule ────────────────────────────────────────────────────────────────────


class Rule(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    slug: str = Field(max_length=128, unique=True, index=True)
    category: IssueCategory
    severity: IssueSeverity
    title: str = Field(max_length=255)
    description: str = Field(max_length=2048)
    enabled: bool = Field(default=True)
    severity_weight: float = Field(default=1.0)
    issues: list["Issue"] = Relationship(back_populates="rule")


# ─── Analysis ────────────────────────────────────────────────────────────────


class Analysis(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    repo_id: uuid.UUID = Field(
        foreign_key="repository.id", nullable=False, ondelete="CASCADE"
    )
    workflow_file_id: uuid.UUID | None = Field(
        default=None, foreign_key="workflow_file.id", nullable=True, ondelete="CASCADE"
    )
    content_hash: str = Field(max_length=64, index=True)
    status: AnalysisStatus = Field(
        default=AnalysisStatus.running,
        sa_column_kwargs={"server_default": AnalysisStatus.running.value},
    )
    score: float | None = Field(default=None)
    grade: str | None = Field(default=None, max_length=8)
    triggered_by: AnalysisTrigger = Field(default=AnalysisTrigger.manual)
    branch: str | None = Field(default=None, max_length=255)
    commit_sha: str | None = Field(default=None, max_length=64)
    error_message: str | None = Field(default=None, max_length=2048)
    # Set when status is ``failed`` to say whether a ``retry`` is worthwhile
    # (transient) or futile until the input changes (permanent).
    failure_kind: AnalysisFailureKind | None = Field(default=None)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    completed_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    repository: Repository | None = Relationship(back_populates="analyses")
    workflow_file: WorkflowFile | None = Relationship(
        back_populates="analyses",
    )
    issues: list["Issue"] = Relationship(back_populates="analysis", cascade_delete=True)


# ─── Issue ───────────────────────────────────────────────────────────────────


class Issue(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "workflow_file_id", "fingerprint", name="uq_issue_wf_fingerprint"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    analysis_id: uuid.UUID = Field(
        foreign_key="analysis.id", nullable=False, ondelete="CASCADE"
    )
    workflow_file_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="workflow_file.id",
        index=True,
        ondelete="CASCADE",
    )
    rule_id: uuid.UUID = Field(
        foreign_key="rule.id", nullable=False, ondelete="RESTRICT"
    )
    job: str | None = Field(default=None, max_length=255)
    step: str | None = Field(default=None, max_length=255)
    step_index: int | None = Field(default=None)
    fingerprint: str | None = Field(default=None, max_length=16, index=True)
    severity: IssueSeverity
    category: IssueCategory
    # Derived from ignored_at + resolved_at + fix_id, but persisted and kept
    # authoritative by a DB trigger (see migrations 0022/0026) so it survives
    # the fix_id ON DELETE SET NULL cascade. Applications never set it directly;
    # the trigger owns writes. To mute/unmute an issue, set/clear ignored_at.
    status: IssueStatus = Field(
        default=IssueStatus.open,
        sa_column_kwargs={"server_default": IssueStatus.open.value},
        index=True,
    )
    line_start: int | None = Field(default=None)
    line_end: int | None = Field(default=None)
    message: str = Field(max_length=2048)
    context: str | None = Field(default=None, max_length=4096)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    resolved_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    # Why the issue resolved (set with resolved_at, cleared on recur). An
    # attribute of the ``resolved`` state, not a separate state.
    resolution_reason: IssueResolutionReason | None = Field(default=None)
    # Set when a user dismisses the violation (false positive / accepted risk);
    # takes precedence in the status trigger so the issue reads ``ignored``.
    ignored_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    fix_id: uuid.UUID | None = Field(
        default=None,
        sa_column=sa.Column(
            sa.UUID,
            sa.ForeignKey("fix.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    analysis: Analysis | None = Relationship(back_populates="issues")
    rule: Rule | None = Relationship(back_populates="issues")
    fix: Optional["Fix"] = Relationship(back_populates="issues")


# ─── PullRequest ──────────────────────────────────────────────────────────────


class PullRequest(SQLModel, table=True):
    __tablename__ = "pull_request"
    __table_args__ = (
        UniqueConstraint("repo_id", "pr_branch", name="uq_pr_repo_branch"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    repo_id: uuid.UUID = Field(
        foreign_key="repository.id", nullable=False, ondelete="CASCADE"
    )
    pr_branch: str = Field(max_length=255, index=True)
    pr_url: str | None = Field(default=None, max_length=1024)
    # NOT NULL since migration 0027 (legacy NULL rows backfilled to ``open``).
    # Kept typed Optional so the defensive NULL guard in state_machines.base
    # still compiles; new rows always default to ``open``.
    pr_state: PullRequestState | None = Field(
        default=PullRequestState.open,
        sa_column_kwargs={"server_default": PullRequestState.open.value},
    )
    comment_url: str | None = Field(default=None, max_length=1024)
    # Enrichment attributes (not machine states): CI outcome, latest review
    # decision and GitHub mergeable_state, populated by check_suite /
    # pull_request_review / pull_request webhooks.
    ci_status: CIStatus | None = Field(default=None)
    review_decision: ReviewDecision | None = Field(default=None)
    mergeable_state: str | None = Field(default=None, max_length=32)
    # A non-bot user pushed commits to the fix branch. Auto-redelivery is
    # blocked while set (it would overwrite the user's edits); a successful
    # forced delivery clears it.
    externally_modified: bool = Field(
        default=False, sa_column_kwargs={"server_default": sa.false()}
    )
    # Polling cursors (external-repo PRs receive no webhooks): the PR head SHA
    # last seen by the poller (a change means new commits, i.e. ``synchronize``)
    # and the timestamp up to which command comments have been processed.
    head_sha: str | None = Field(default=None, max_length=40)
    last_polled_comment_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    updated_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    repository: Repository | None = Relationship(back_populates="pull_requests")
    fixes: list["Fix"] = Relationship(back_populates="pull_request")


# ─── Fix ─────────────────────────────────────────────────────────────────────


class Fix(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    workflow_file_id: uuid.UUID = Field(
        foreign_key="workflow_file.id", unique=True, nullable=False, ondelete="CASCADE"
    )
    pr_id: uuid.UUID | None = Field(
        default=None,
        sa_column=sa.Column(
            sa.UUID,
            sa.ForeignKey("pull_request.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    llm_provider: LLMProvider
    llm_model: str = Field(max_length=255)
    prompt_tokens: int | None = Field(default=None)
    completion_tokens: int | None = Field(default=None)
    langsmith_run_id: str | None = Field(default=None, max_length=255)
    status: FixStatus = Field(default=FixStatus.pending)
    full_content: str | None = Field(default=None)
    error_message: str | None = Field(default=None, max_length=2048)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    delivered_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    workflow_file: WorkflowFile | None = Relationship(back_populates="fix")
    issues: list[Issue] = Relationship(back_populates="fix")
    pull_request: Optional["PullRequest"] = Relationship(back_populates="fixes")


# ─── TelemetryRun ─────────────────────────────────────────────────────────────


class TelemetryRun(SQLModel, table=True):
    __tablename__ = "telemetry_run"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    repo_id: uuid.UUID = Field(
        foreign_key="repository.id", nullable=False, ondelete="CASCADE"
    )
    workflow_run_id: int = Field(index=True)
    runner_specs: str | None = Field(default=None)
    metrics: str | None = Field(default=None)
    phase: TelemetryPhase | None = Field(default=None)
    # Dynamic-analysis lifecycle for a ``completed``-phase run (owned by the
    # TelemetryMachine); NULL for ``started``-phase rows, which never enrich.
    dynamic_status: DynamicAnalysisStatus | None = Field(default=None)
    collected_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    repository: Repository | None = Relationship(back_populates="telemetry_runs")


# ─── DynamicEnrichment ────────────────────────────────────────────────────────


class DynamicEnrichment(SQLModel, table=True):
    """A runtime-telemetry finding produced by dynamic analysis.

    Persisted (rather than only logged) so the recommendations a telemetry run
    surfaces — e.g. an oversized runner — are queryable and can be shown
    alongside the repo's static findings. Linked to the telemetry run that
    produced it and, when available, the latest completed analysis it enriches.
    """

    __tablename__ = "dynamic_enrichment"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    repo_id: uuid.UUID = Field(
        foreign_key="repository.id", nullable=False, ondelete="CASCADE"
    )
    telemetry_run_id: uuid.UUID = Field(
        foreign_key="telemetry_run.id", nullable=False, ondelete="CASCADE"
    )
    analysis_id: uuid.UUID | None = Field(
        default=None,
        sa_column=sa.Column(
            sa.UUID,
            sa.ForeignKey("analysis.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    rule_slug: str = Field(max_length=128, index=True)
    evidence: str = Field(max_length=2048)
    recommendation: str = Field(max_length=2048)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )


# ─── TelemetryMetricSample ────────────────────────────────────────────────────


class TelemetryMetricSample(SQLModel, table=True):
    __tablename__ = "telemetry_metric_sample"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    repo_id: uuid.UUID = Field(
        foreign_key="repository.id", nullable=False, ondelete="CASCADE"
    )
    workflow_run_id: int = Field(index=True)
    sampled_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    cpu_percent: float | None = Field(default=None)
    ram_used_mb: float | None = Field(default=None)
    disk_used_gb: float | None = Field(default=None)
    net_bytes_sent: int | None = Field(default=None)
    net_bytes_recv: int | None = Field(default=None)


# ─── BillingSubscription ─────────────────────────────────────────────────────


class BillingSubscription(SQLModel, table=True):
    __tablename__ = "billing_subscription"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", unique=True, nullable=False, ondelete="CASCADE"
    )
    tier: UserTier = Field(default=UserTier.free)
    stripe_subscription_id: str | None = Field(
        default=None, max_length=255, unique=True
    )
    stripe_customer_id: str | None = Field(default=None, max_length=255)
    analyses_used: int = Field(default=0)
    fixes_used: int = Field(default=0)
    period_start: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    period_end: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    user: Optional["User"] = Relationship(back_populates="billing_subscription")
