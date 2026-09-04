"""Repositories, their workflow files, pull requests and the rule catalog."""

import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from ..enums import (
    Category,
    CIStatus,
    Engine,
    PullRequestState,
    ReviewDecision,
    ScanStatus,
    Severity,
    TargetActivity,
    UserTier,
)


class RepoEngineGrade(SQLModel):
    """One engine's average grade for a repository.

    Only engines that have actually scored the repo appear. An engine that has
    never run has no entry, which is a different statement from a bad grade and
    is what lets a page render "—" rather than an invented letter.
    """

    engine: Engine
    score: float
    grade: str


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
    # What the CI engine is doing to this repository right now, under the same
    # name ``ScanTargetPublicBase`` uses for the file engines' targets — a
    # repository is the CI engine's target, and giving the concept two names
    # would leave the UI unable to ask one question of every engine. Unfinished
    # beats newest (see ``_latest_scan_statuses_batch``), so it says "a scan is
    # running" even when a sibling workflow file's scan has already landed.
    # ``None`` on the reads that do not compute it.
    latest_scan_status: ScanStatus | None = None
    # What the repository is busy with, under the same name and the same rules
    # ``ScanTargetPublicBase.activity`` uses — a repository *is* the CI engine's
    # target. Computed by ``engine_routes.repository_activities``, which is the
    # batched form of what the 409 guard asks, so the field and the refusal it
    # predicts are one answer. ``idle`` on the reads that do not compute it.
    activity: TargetActivity = TargetActivity.idle
    # The CI-workflow average, kept under its historical names because badges,
    # the dashboard and the repository list all read them. It is the same
    # number as the `workflow` entry in `engine_grades`.
    avg_score: float | None = None
    grade: str | None = None
    # Every engine's own average, so each engine's page shows its own grade
    # rather than the CI one or the worst of its targets'.
    engine_grades: list[RepoEngineGrade] = []


class ExternalRepositoryCreate(SQLModel):
    full_name: str = Field(max_length=512)
    installation_id: int | None = None


class WorkflowFilePublic(SQLModel):
    id: uuid.UUID
    path: str
    branch: str | None = None
    raw_content: str | None = None
    # Provenance of ``raw_content``, so the UI can say which commit is on screen
    # and how long ago it was verified rather than implying it is live.
    source_commit_sha: str | None = None
    fetched_at: datetime | None = None


class WorkflowSyncSummary(SQLModel):
    """What a manual "sync from GitHub" run changed, for the toast in the UI.

    ``head_sha`` is None when the branch head could not be resolved, in which
    case the sync read a mutable ref and reconciled nothing it wasn't sure of.
    """

    branch: str
    head_sha: str | None = None
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    restored: int = 0
    deleted: int = 0
    skipped_stale: int = 0


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


class RepositoryUpdate(SQLModel):
    """The two switches a repository owner can flip.

    Both are optional: a ``PATCH`` naming only one leaves the other alone.
    Enabling either is quota-checked, which is why they are not a blanket
    "update the repository" body — nothing else about a repo is user-writable.
    """

    enabled: bool | None = None
    auto_fix_enabled: bool | None = None


class RuleUpdate(SQLModel):
    """A rule's catalog-wide on/off switch."""

    enabled: bool | None = None
