"""The CI-workflow engine: scans, findings, fixes and finding statistics."""

import uuid

from sqlmodel import SQLModel

from ..enums import Category, Severity
from .base import FileFixPublicBase, FixablePublicBase, RepoScanPublicBase


class WorkflowScanPublic(RepoScanPublicBase):
    """One static-analysis run over a repository's workflow files."""

    repo_id: uuid.UUID
    workflow_file_id: uuid.UUID | None = None
    file_path: str | None = None
    repo_full_name: str | None = None
    content_hash: str


class WorkflowFindingPublic(FixablePublicBase):
    """A rule violation in a workflow file."""

    file_path: str | None = None
    # 1-based line span of the offending step or job block, so the frontend can
    # annotate the finding inline on the source.
    line_start: int | None = None
    line_end: int | None = None
    # Set when the violation cannot be rewritten automatically — the LLM is
    # told to leave it alone and the UI explains why.
    needs_manual_work: bool = False
    manual_work_note: str | None = None


class FindingCategoryStat(SQLModel):
    category: Category
    open: int
    resolved: int
    critical_open: int


class RepoCategoryStat(SQLModel):
    """A repo's open-finding counts and severity-weighted grade for one category.

    ``score``/``grade`` are ``None`` when the repo has no overall grade yet
    (e.g. no completed scan). See ``RepoFindingStats`` for how categories
    are grouped per repo.
    """

    category: Category
    open: int
    critical_open: int
    score: float | None = None
    grade: str | None = None


class RepoFindingStats(SQLModel):
    """Per-repo finding breakdown — powers the dashboard's category health star
    diagram. Only populated on the unscoped (all-repos) stats call;
    meaningless once already filtered to a single ``repo_id``.

    ``score``/``grade`` here are the repo's own overall grade (same values as
    ``RepositoryPublic.avg_score``/``grade``), repeated so the frontend
    doesn't need a second lookup to size the radar's "no findings" fallback.
    Each entry in ``categories`` covers every ``Category``, including
    categories with zero open findings, so their scores average out to exactly
    the repo's overall score (see ``compute_category_scores``).
    """

    repo_id: uuid.UUID
    score: float | None = None
    grade: str | None = None
    categories: list[RepoCategoryStat] = []


class WorkflowFindingStatsPublic(SQLModel):
    """Exact finding counts, computed by SQL aggregation rather than fetched and
    counted client-side — unaffected by any page's ``skip``/``limit``."""

    total_open: int
    total_resolved: int
    critical_open: int
    by_category: list[FindingCategoryStat]
    by_repo: list[RepoFindingStats] = []


class FixFindingSummary(SQLModel):
    """The findings one fix set out to resolve, as the fix detail view lists them."""

    id: uuid.UUID
    rule_slug: str | None = None
    severity: Severity | None = None
    category: Category | None = None
    message: str | None = None
    line_start: int | None = None
    line_end: int | None = None


class WorkflowFixPublic(FileFixPublicBase):
    """An LLM rewrite of one workflow file."""

    workflow_file_id: uuid.UUID
    repo_id: uuid.UUID | None = None
    # The content the rewrite was based on, so the UI can diff without
    # re-fetching the file from GitHub.
    base_content: str | None = None
    comment_url: str | None = None
    findings: list[FixFindingSummary] = []
