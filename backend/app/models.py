import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import EmailStr
from sqlalchemy import DateTime
from sqlmodel import Field, Relationship, SQLModel


def get_datetime_utc() -> datetime:
    return datetime.now(timezone.utc)


# ─── Enums ───────────────────────────────────────────────────────────────────


class UserTier(str, enum.Enum):
    free = "free"
    starter = "starter"
    pro = "pro"
    ultimate = "ultimate"
    open_source = "open_source"


class OrgRole(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    member = "member"


class FixDeliveryMode(str, enum.Enum):
    pr = "pr"
    comment = "comment"
    disabled = "disabled"


class LLMProvider(str, enum.Enum):
    openai = "openai"
    anthropic = "anthropic"
    gemini = "gemini"
    ollama = "ollama"


class AnalysisStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"  # dedup hit


class AnalysisTrigger(str, enum.Enum):
    webhook_push = "webhook_push"
    webhook_workflow_run = "webhook_workflow_run"
    manual = "manual"
    scheduled = "scheduled"


class IssueSeverity(str, enum.Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"
    info = "info"


class IssueCategory(str, enum.Enum):
    energy = "energy"
    reliability = "reliability"
    security = "security"
    performance = "performance"
    maintainability = "maintainability"


class FixStatus(str, enum.Enum):
    pending = "pending"
    generating = "generating"
    ready = "ready"
    delivering = "delivering"
    delivered = "delivered"
    failed = "failed"
    rejected = "rejected"


# ─── User ────────────────────────────────────────────────────────────────────


# Shared properties
class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on creation
class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on update, all are optional
class UserUpdate(UserBase):
    email: EmailStr | None = Field(default=None, max_length=255)  # type: ignore[assignment]
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


# Database model, database table inferred from class name
class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    github_id: int | None = Field(default=None, unique=True, index=True)
    github_username: str | None = Field(default=None, max_length=255)
    tier: UserTier = Field(default=UserTier.free)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    org_memberships: list["OrgMember"] = Relationship(
        back_populates="user", cascade_delete=True
    )
    billing_subscription: Optional["BillingSubscription"] = Relationship(
        back_populates="user"
    )


# Properties to return via API, id is always required
class UserPublic(UserBase):
    id: uuid.UUID
    github_username: str | None = None
    tier: UserTier = UserTier.free
    created_at: datetime | None = None


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


# ─── Organization ────────────────────────────────────────────────────────────


class Organization(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    github_org_id: int | None = Field(default=None, unique=True, index=True)
    name: str = Field(max_length=255, index=True)
    tier: UserTier = Field(default=UserTier.free)
    default_llm_provider: LLMProvider = Field(default=LLMProvider.openai)
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
    full_name: str = Field(max_length=512, index=True)  # e.g. "owner/repo"
    installation_id: int = Field(index=True)
    enabled: bool = Field(default=True)
    default_branch: str = Field(default="main", max_length=255)
    fix_delivery_mode: FixDeliveryMode | None = Field(
        default=None
    )  # overrides org default
    llm_provider: LLMProvider | None = Field(default=None)  # overrides org default
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


# ─── WorkflowFile ─────────────────────────────────────────────────────────────


class WorkflowFile(SQLModel, table=True):
    __tablename__ = "workflow_file"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    repo_id: uuid.UUID = Field(
        foreign_key="repository.id", nullable=False, ondelete="CASCADE"
    )
    path: str = Field(max_length=512)  # e.g. ".github/workflows/ci.yml"
    content_hash: str = Field(max_length=64, index=True)  # SHA-256 hex
    raw_content: str  # full YAML text
    fetched_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    repository: Repository | None = Relationship(back_populates="workflow_files")
    analyses: list["Analysis"] = Relationship(back_populates="workflow_file")


# ─── Rule ────────────────────────────────────────────────────────────────────


class Rule(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    slug: str = Field(max_length=128, unique=True, index=True)  # e.g. "missing_timeout"
    category: IssueCategory
    severity: IssueSeverity
    title: str = Field(max_length=255)
    description: str = Field(max_length=2048)
    enabled: bool = Field(default=True)
    severity_weight: float = Field(default=1.0)  # for score calculation
    issues: list["Issue"] = Relationship(back_populates="rule")


# ─── Analysis ────────────────────────────────────────────────────────────────


class Analysis(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    repo_id: uuid.UUID = Field(
        foreign_key="repository.id", nullable=False, ondelete="CASCADE"
    )
    workflow_file_id: uuid.UUID = Field(
        foreign_key="workflow_file.id", nullable=False, ondelete="CASCADE"
    )
    content_hash: str = Field(max_length=64, index=True)  # dedup key
    status: AnalysisStatus = Field(default=AnalysisStatus.pending)
    score: float | None = Field(default=None)  # 0-100
    grade: str | None = Field(default=None, max_length=8)  # "A+++", "B", "F", etc.
    triggered_by: AnalysisTrigger = Field(default=AnalysisTrigger.manual)
    branch: str | None = Field(default=None, max_length=255)
    commit_sha: str | None = Field(default=None, max_length=64)
    error_message: str | None = Field(default=None, max_length=2048)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    completed_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    repository: Repository | None = Relationship(back_populates="analyses")
    workflow_file: WorkflowFile | None = Relationship(back_populates="analyses")
    issues: list["Issue"] = Relationship(back_populates="analysis", cascade_delete=True)


# ─── Issue ───────────────────────────────────────────────────────────────────


class Issue(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    analysis_id: uuid.UUID = Field(
        foreign_key="analysis.id", nullable=False, ondelete="CASCADE"
    )
    rule_id: uuid.UUID = Field(
        foreign_key="rule.id", nullable=False, ondelete="RESTRICT"
    )
    severity: IssueSeverity
    category: IssueCategory
    line_start: int | None = Field(default=None)
    line_end: int | None = Field(default=None)
    message: str = Field(max_length=2048)
    context: str | None = Field(default=None, max_length=4096)  # JSON snippet from YAML
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    analysis: Analysis | None = Relationship(back_populates="issues")
    rule: Rule | None = Relationship(back_populates="issues")
    fix: Optional["Fix"] = Relationship(back_populates="issue")


# ─── Fix ─────────────────────────────────────────────────────────────────────


class Fix(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    issue_id: uuid.UUID = Field(
        foreign_key="issue.id", unique=True, nullable=False, ondelete="CASCADE"
    )
    llm_provider: LLMProvider
    llm_model: str = Field(max_length=255)
    prompt_tokens: int | None = Field(default=None)
    completion_tokens: int | None = Field(default=None)
    langsmith_run_id: str | None = Field(default=None, max_length=255)
    status: FixStatus = Field(default=FixStatus.pending)
    diff: str | None = Field(default=None)  # unified diff text
    pr_url: str | None = Field(default=None, max_length=1024)
    comment_url: str | None = Field(default=None, max_length=1024)
    error_message: str | None = Field(default=None, max_length=2048)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    delivered_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    issue: Issue | None = Relationship(back_populates="fix")


# ─── TelemetryRun ─────────────────────────────────────────────────────────────


class TelemetryRun(SQLModel, table=True):
    __tablename__ = "telemetry_run"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    repo_id: uuid.UUID = Field(
        foreign_key="repository.id", nullable=False, ondelete="CASCADE"
    )
    workflow_run_id: int = Field(index=True)
    runner_specs: str | None = Field(
        default=None
    )  # JSON: vcpus, ram_gb, location, etc.
    metrics: str | None = Field(default=None)  # JSON: cpu_pct, ram_mb, net_io, etc.
    collected_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    repository: Repository | None = Relationship(back_populates="telemetry_runs")


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


# ─── Public / response schemas ────────────────────────────────────────────────


class OrganizationPublic(SQLModel):
    id: uuid.UUID
    name: str
    tier: UserTier
    default_llm_provider: LLMProvider
    fix_delivery_mode: FixDeliveryMode
    created_at: datetime | None = None


class RepositoryPublic(SQLModel):
    id: uuid.UUID
    full_name: str
    enabled: bool
    default_branch: str
    tier: UserTier | None = None  # inherited from org
    created_at: datetime | None = None


class AnalysisPublic(SQLModel):
    id: uuid.UUID
    repo_id: uuid.UUID
    workflow_file_id: uuid.UUID
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
    severity: IssueSeverity
    category: IssueCategory
    line_start: int | None = None
    line_end: int | None = None
    message: str
    context: str | None = None
    created_at: datetime | None = None


class FixPublic(SQLModel):
    id: uuid.UUID
    issue_id: uuid.UUID
    llm_provider: LLMProvider
    llm_model: str
    status: FixStatus
    diff: str | None = None
    pr_url: str | None = None
    comment_url: str | None = None
    created_at: datetime | None = None
    delivered_at: datetime | None = None


class RulePublic(SQLModel):
    id: uuid.UUID
    slug: str
    category: IssueCategory
    severity: IssueSeverity
    title: str
    description: str
    enabled: bool


class BillingSubscriptionPublic(SQLModel):
    id: uuid.UUID
    tier: UserTier
    analyses_used: int
    fixes_used: int
    period_start: datetime | None = None
    period_end: datetime | None = None


# ─── Generic utility schemas ──────────────────────────────────────────────────


# Generic message
class Message(SQLModel):
    message: str


# JSON payload containing access token
class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


# Contents of JWT token
class TokenPayload(SQLModel):
    sub: str | None = None


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)
