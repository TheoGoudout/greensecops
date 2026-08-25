"""The CI-workflow engine: scans, findings, fixes and issue statistics."""

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


class AnalysisPublic(SQLModel):
    id: uuid.UUID
    repo_id: uuid.UUID
    workflow_file_id: uuid.UUID | None = None
    workflow_file_path: str | None = None
    repo_full_name: str | None = None
    content_hash: str
    status: ScanStatus
    score: float | None = None
    grade: str | None = None
    triggered_by: ScanTrigger
    branch: str | None = None
    commit_sha: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None


class IssuePublic(SQLModel):
    id: uuid.UUID
    analysis_id: uuid.UUID
    rule_id: uuid.UUID
    rule_slug: str
    severity: Severity
    category: Category
    line_start: int | None = None
    line_end: int | None = None
    message: str
    context: str | None = None
    status: FindingStatus
    created_at: datetime | None = None
    resolved_at: datetime | None = None
    resolution_reason: FindingResolutionReason | None = None
    needs_manual_work: bool = False
    manual_work_note: str | None = None
    fix_id: uuid.UUID | None = None
    fix_status: FixStatus | None = None
    workflow_file_path: str | None = None


class IssueCategoryStat(SQLModel):
    category: Category
    open: int
    resolved: int
    critical_open: int


class RepoCategoryStat(SQLModel):
    """A repo's open-issue counts and severity-weighted grade for one category.

    ``score``/``grade`` are ``None`` when the repo has no overall grade yet
    (e.g. no completed analysis). See ``RepoIssueStats`` for how categories
    are grouped per repo.
    """

    category: Category
    open: int
    critical_open: int
    score: float | None = None
    grade: str | None = None


class RepoIssueStats(SQLModel):
    """Per-repo issue breakdown — powers the dashboard's category health star
    diagram. Only populated on the unscoped (all-repos) stats call;
    meaningless once already filtered to a single ``repo_id``.

    ``score``/``grade`` here are the repo's own overall grade (same values as
    ``RepositoryPublic.avg_score``/``grade``), repeated so the frontend
    doesn't need a second lookup to size the radar's "no issues" fallback.
    Each entry in ``categories`` covers every ``Category``, including
    categories with zero open issues, so their scores average out to exactly
    the repo's overall score (see ``compute_category_scores``).
    """

    repo_id: uuid.UUID
    score: float | None = None
    grade: str | None = None
    categories: list[RepoCategoryStat] = []


class IssueStatsPublic(SQLModel):
    """Exact issue counts, computed by SQL aggregation rather than fetched and
    counted client-side — unaffected by any page's ``skip``/``limit``."""

    total_open: int
    total_resolved: int
    critical_open: int
    by_category: list[IssueCategoryStat]
    by_repo: list[RepoIssueStats] = []


class FixIssueSummary(SQLModel):
    id: uuid.UUID
    rule_slug: str | None = None
    severity: Severity | None = None
    category: Category | None = None
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
    comment_url: str | None = None
    created_at: datetime | None = None
    delivered_at: datetime | None = None
    issues: list[FixIssueSummary] = []
