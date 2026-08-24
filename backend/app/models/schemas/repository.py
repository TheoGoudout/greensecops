"""Repositories, their workflow files, pull requests and the rule catalog."""

import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from ..enums import (
    Category,
    CIStatus,
    PullRequestState,
    ReviewDecision,
    Severity,
    UserTier,
)


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
    category: Category
    severity: Severity
    title: str
    description: str
    enabled: bool
