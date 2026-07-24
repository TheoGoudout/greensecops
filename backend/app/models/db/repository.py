import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime
from sqlmodel import Field, Relationship, SQLModel

from ..enums import FixDeliveryMode, LLMProvider, RepositoryStatus
from .base import get_datetime_utc

if TYPE_CHECKING:
    from .analysis import Analysis
    from .organization import Organization
    from .pull_request import PullRequest
    from .telemetry import TelemetryRun
    from .terraform import TerraformRoot
    from .workflow_file import WorkflowFile


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
    organization: Optional["Organization"] = Relationship(back_populates="repositories")
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
    terraform_roots: list["TerraformRoot"] = Relationship(
        back_populates="repository", cascade_delete=True
    )
