"""Shapes every engine's public models are built from.

A scan, a finding, a scanned file and a file-level fix look the same from
outside whichever engine produced them; only the locator columns differ. These
bases hold what they share, and each engine's module adds its own."""

import uuid
from datetime import datetime

from sqlmodel import SQLModel

from ..enums import (
    Category,
    FindingResolutionReason,
    FindingStatus,
    FixStatus,
    LLMProvider,
    PullRequestState,
    ScanStatus,
    ScanTrigger,
    Severity,
)


class ScanPublicBase(SQLModel):
    """One engine run, as the UI shows it in a scan history list."""

    id: uuid.UUID
    status: ScanStatus
    triggered_by: ScanTrigger
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
    severity: Severity
    category: Category
    message: str
    context: str | None = None
    status: FindingStatus
    created_at: datetime | None = None
    resolved_at: datetime | None = None
    resolution_reason: FindingResolutionReason | None = None


class FixablePublicBase(FindingPublicBase):
    """A finding an engine can generate a fix for — mirrors
    ``WorkflowFindingPublic.fix_id``/``fix_status``. Cloud findings have no fix pipeline,
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
    # The most recent scan's status regardless of outcome — unlike
    # `latest_grade`, which only ever reflects a *completed* scan — so the UI
    # can show a target is currently being scanned.
    latest_scan_status: ScanStatus | None = None
    badge_sig: str | None = None


class ScanTargetUpdate(SQLModel):
    """The mutable part of a registered scan target.

    Every engine enables and disables its target the same way, so one body
    serves all of them rather than three identical copies. Optional so a
    ``PATCH`` that omits the field leaves it alone.
    """

    enabled: bool | None = None
