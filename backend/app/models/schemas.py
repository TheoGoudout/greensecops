import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from .db import UserBase
from .enums import (
    AnalysisStatus,
    AnalysisTrigger,
    FixDeliveryMode,
    FixStatus,
    IssueCategory,
    IssueSeverity,
    IssueStatus,
    LLMProvider,
    PullRequestState,
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
    default_branch: str
    auto_fix_enabled: bool = False
    tier: UserTier | None = None
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
    fix_id: uuid.UUID | None = None
    fix_status: FixStatus | None = None
    workflow_file_path: str | None = None


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
    created_at: datetime | None = None
    delivered_at: datetime | None = None
    issues: list[FixIssueSummary] = []


class WorkflowFilePublic(SQLModel):
    id: uuid.UUID
    path: str
    raw_content: str | None = None


class PullRequestPublic(SQLModel):
    id: uuid.UUID
    repo_id: uuid.UUID
    pr_branch: str
    pr_url: str | None = None
    pr_state: PullRequestState | None = None
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
