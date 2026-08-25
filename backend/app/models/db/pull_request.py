import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlalchemy import DateTime, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from ..enums import CIStatus, PullRequestState, ReviewDecision
from .base import get_datetime_utc

if TYPE_CHECKING:
    from .ansible import AnsibleFix
    from .docker import DockerFix
    from .repository import Repository
    from .terraform import TerraformFix
    from .workflow_fix import WorkflowFix


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
    repository: Optional["Repository"] = Relationship(back_populates="pull_requests")
    fixes: list["WorkflowFix"] = Relationship(back_populates="pull_request")
    ansible_fixes: list["AnsibleFix"] = Relationship(back_populates="pull_request")
    terraform_fixes: list["TerraformFix"] = Relationship(back_populates="pull_request")
    docker_fixes: list["DockerFix"] = Relationship(back_populates="pull_request")
