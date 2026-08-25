"""Column sets shared by the per-engine tables.

GreenSecOps runs one analysis engine per domain (CI workflow, Terraform,
Docker/Compose, AWS cloud posture), and each keeps its own tables — a Terraform
finding and a Docker finding are stored separately because their locators
differ, and because the engines are deployed and reasoned about independently.
What they emphatically do *not* differ in is the lifecycle scaffolding around
those locators: every scan has the same status/trigger/score/grade/failure
columns, and every finding the same rule/fingerprint/severity/resolution ones.

Those shared columns used to be retyped in full in each table. These mixins are
that boilerplate written once. They are plain non-table ``SQLModel`` bases, so
each concrete table still gets its own ``Column`` objects and its own DDL —
nothing is shared at the database level, only the declaration.

**These must not change the schema.** ``backend/scripts/schema_snapshot.py``
dumps an order-insensitive view of the metadata for exactly that check; a
column moved in here must leave it byte-identical. Note that inheritance puts
mixin columns first in ``CREATE TABLE``, which is why that script compares
structure rather than statement text.

Anything genuinely per-engine — the locators a rule reports, the foreign key to
the owning root/target/account, Docker's ``file_count``, cloud's ``region`` —
stays declared on the table itself, where it can be read and commented in
context.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime
from sqlmodel import Field, SQLModel

from ..enums import (
    Category,
    FindingResolutionReason,
    FindingStatus,
    FixStatus,
    LLMProvider,
    ScanFailureKind,
    ScanStatus,
    ScanTrigger,
    Severity,
)
from .base import get_datetime_utc


class ScanTargetMixin(SQLModel):
    """A repo folder registered for scanning — a Terraform root, a Docker target.

    ``root_path`` is deliberately absent: a Terraform root must be given one
    explicitly, while a Docker target defaults to ``""`` (the repository root,
    created automatically during installation sync). Same column, different
    contract, so each table states its own.
    """

    repo_id: uuid.UUID = Field(
        foreign_key="repository.id", nullable=False, ondelete="CASCADE"
    )
    enabled: bool = Field(default=True)
    # Polling/webhook cursor, mirroring Repository.last_polled_head_sha: the
    # default-branch head last scanned, so a push that doesn't touch this
    # target's files can be skipped cheaply.
    last_scanned_head_sha: str | None = Field(default=None, max_length=40)
    last_scanned_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )


class ScanMixin(SQLModel):
    """One run of an engine over its target, and how it ended.

    ``failure_kind`` is orthogonal to ``status``: it says whether a ``failed``
    scan is worth retrying in place, which the maintenance sweeper reads.
    """

    status: ScanStatus = Field(
        default=ScanStatus.queued,
        sa_column_kwargs={"server_default": ScanStatus.queued.value},
    )
    triggered_by: ScanTrigger = Field(default=ScanTrigger.manual)
    score: float | None = Field(default=None)
    grade: str | None = Field(default=None, max_length=8)
    error_message: str | None = Field(default=None, max_length=2048)
    failure_kind: ScanFailureKind | None = Field(default=None)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    completed_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))


class RepoScanMixin(ScanMixin):
    """A scan of code in a git repository, which a cloud-account scan is not:
    it happened at a commit on a branch, and both are worth recording."""

    branch: str | None = Field(default=None, max_length=255)
    commit_sha: str | None = Field(default=None, max_length=64)


class FindingMixin(SQLModel):
    """A rule violation persisted against its target, with its lifecycle.

    ``fingerprint`` is the identity that survives a re-scan (see
    ``services/deduplication.compute_fingerprint``), which is what lets
    ``resolved_at``/``ignored_at`` mean anything: without it every scan would
    insert fresh rows and drop the user's dismissals.

    Unlike ``WorkflowFinding.status`` — owned by a DB trigger reacting to ``fix_id`` —
    this ``status`` is set directly by the application alongside the two
    timestamps.
    """

    rule_id: uuid.UUID = Field(
        foreign_key="rule.id", nullable=False, ondelete="RESTRICT"
    )
    fingerprint: str = Field(max_length=16, index=True)
    severity: Severity
    category: Category
    status: FindingStatus = Field(
        default=FindingStatus.open,
        sa_column_kwargs={"server_default": FindingStatus.open.value},
        index=True,
    )
    message: str = Field(max_length=2048)
    context: str | None = Field(default=None, max_length=4096)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    resolved_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    resolution_reason: FindingResolutionReason | None = Field(default=None)
    ignored_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))


class FileFixMixin(SQLModel):
    """An LLM-generated rewrite of one file, and the PR it was delivered on.

    Terraform and Docker files aren't persisted as their own rows, so the unit
    a fix targets is a ``(target, file_path)`` pair rather than a file id —
    which is why ``file_path`` lives here and the target FK does not.

    ``pr_id`` is ``SET NULL`` rather than ``CASCADE``: dropping a pull request
    must not delete the fix that produced it.
    """

    file_path: str = Field(max_length=512)
    pr_id: uuid.UUID | None = Field(
        default=None, foreign_key="pull_request.id", ondelete="SET NULL"
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


class EnrichmentMixin(SQLModel):
    """A measured finding produced from telemetry rather than from source.

    Deliberately thinner than a ``FindingMixin`` table: no fingerprint, no
    dedup and no resolution lifecycle, because a measurement is a fact about
    one observed run, not a defect that persists until fixed. It carries a
    bare ``rule_slug`` rather than a ``rule_id`` for the same reason — a Rego
    rule shipped without a catalog row still produces valid observations.
    """

    repo_id: uuid.UUID = Field(
        foreign_key="repository.id", nullable=False, ondelete="CASCADE"
    )
    rule_slug: str = Field(max_length=128, index=True)
    evidence: str = Field(max_length=2048)
    recommendation: str = Field(max_length=2048)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
