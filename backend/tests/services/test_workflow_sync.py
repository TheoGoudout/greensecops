"""Tests for the workflow-file sync step.

This service owns ``WorkflowFile`` state, so these cover the two properties the
rest of the pipeline leans on: content is persisted independently of whether an
analysis runs, and a write never goes backwards in time.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlmodel import Session, select

from app.models import (
    Analysis,
    AnalysisStatus,
    AnalysisTrigger,
    Fix,
    FixStatus,
    Issue,
    IssueCategory,
    IssueResolutionReason,
    IssueSeverity,
    LLMProvider,
    Organization,
    Repository,
    Rule,
    RuleDomain,
    UserTier,
    WorkflowFile,
)
from app.services.github.app_client import WorkflowFileContent
from app.services.workflow_sync import (
    WorkflowFetchError,
    sync_workflow_files,
)

HEAD = "a" * 40
LATER_HEAD = "b" * 40

# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def org(db: Session) -> Organization:
    organization = Organization(
        name=f"sync-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free
    )
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization


@pytest.fixture()
def repo(db: Session, org: Organization) -> Repository:
    repository = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"syncowner/repo-{uuid.uuid4().hex[:8]}",
        installation_id=11111,
        enabled=True,
    )
    db.add(repository)
    db.commit()
    db.refresh(repository)
    return repository


def _file(path: str, content: str) -> WorkflowFileContent:
    return WorkflowFileContent(
        path=path, content=content, content_hash="unused", sha="blob"
    )


def _sync(
    session: Session,
    repo: Repository,
    files: list[WorkflowFileContent],
    *,
    head: str | None = HEAD,
    branch: str | None = None,
    reconcile_missing: bool = True,
):  # type: ignore[no-untyped-def]
    return sync_workflow_files(
        session,
        repo,
        branch or repo.default_branch,
        fetch=lambda _repo, _ref: files,
        resolve_sha=lambda _repo, _branch: head,
        reconcile_missing=reconcile_missing,
    )


# ─── Classification ──────────────────────────────────────────────────────────


def test_added_updated_and_unchanged_are_classified(
    db: Session, repo: Repository
) -> None:
    path = ".github/workflows/ci.yml"

    first = _sync(db, repo, [_file(path, "on: push\n")])
    assert first.added == [path]
    assert first.updated == []

    second = _sync(db, repo, [_file(path, "on: pull_request\n")])
    assert second.updated == [path]
    assert second.added == []

    third = _sync(db, repo, [_file(path, "on: pull_request\n")])
    assert third.unchanged == [path]
    assert third.updated == []


def test_provenance_is_written_even_when_content_is_unchanged(
    db: Session, repo: Repository
) -> None:
    """ "Unchanged" must stay distinguishable from "never checked"."""
    path = ".github/workflows/ci.yml"
    _sync(db, repo, [_file(path, "on: push\n")])

    db.expire_all()
    wf = db.exec(select(WorkflowFile).where(WorkflowFile.repo_id == repo.id)).one()
    first_seen = wf.fetched_at

    result = _sync(db, repo, [_file(path, "on: push\n")], head=LATER_HEAD)
    assert result.unchanged == [path]

    db.expire_all()
    wf = db.exec(select(WorkflowFile).where(WorkflowFile.repo_id == repo.id)).one()
    assert wf.source_commit_sha == LATER_HEAD
    assert first_seen is not None and wf.fetched_at is not None
    assert wf.fetched_at > first_seen


def test_a_missing_path_is_soft_deleted_and_its_issues_resolved(
    db: Session, repo: Repository
) -> None:
    path = ".github/workflows/gone.yml"
    _sync(db, repo, [_file(path, "on: push\n")])

    db.expire_all()
    wf = db.exec(select(WorkflowFile).where(WorkflowFile.repo_id == repo.id)).one()

    rule = db.exec(
        select(Rule).where(Rule.domain == RuleDomain.workflow).limit(1)
    ).first()
    assert rule is not None
    analysis = Analysis(
        repo_id=repo.id,
        workflow_file_id=wf.id,
        content_hash=wf.content_hash,
        status=AnalysisStatus.completed,
        triggered_by=AnalysisTrigger.manual,
        branch=repo.default_branch,
    )
    db.add(analysis)
    db.flush()
    issue = Issue(
        analysis_id=analysis.id,
        workflow_file_id=wf.id,
        rule_id=rule.id,
        fingerprint=uuid.uuid4().hex[:16],
        severity=IssueSeverity.high,
        category=IssueCategory.security,
        message="something",
    )
    fix = Fix(
        workflow_file_id=wf.id,
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o-mini",
        status=FixStatus.ready,
        full_content="on: push\n",
    )
    db.add(issue)
    db.add(fix)
    db.commit()

    result = _sync(db, repo, [])
    assert result.deleted == [path]

    db.refresh(wf)
    db.refresh(issue)
    db.refresh(fix)
    assert wf.deleted_at is not None
    assert issue.resolved_at is not None
    assert issue.resolution_reason == IssueResolutionReason.file_removed
    assert fix.status == FixStatus.superseded_by_deleted_file


def test_a_reappearing_path_is_restored(db: Session, repo: Repository) -> None:
    path = ".github/workflows/back.yml"
    _sync(db, repo, [_file(path, "on: push\n")])
    _sync(db, repo, [])

    result = _sync(db, repo, [_file(path, "on: push\n")])
    assert result.restored == [path]

    db.expire_all()
    wf = db.exec(select(WorkflowFile).where(WorkflowFile.repo_id == repo.id)).one()
    assert wf.deleted_at is None


# ─── The write-ordering guard ────────────────────────────────────────────────


def test_a_sync_that_resolved_earlier_does_not_overwrite_newer_content(
    db: Session, repo: Repository
) -> None:
    """The defect that made a delayed webhook clobber a newer push.

    The lock serialises analyses but orders nothing, so the run that *executes*
    last is not necessarily the run that read the newest commit.
    """
    path = ".github/workflows/ci.yml"
    _sync(db, repo, [_file(path, "new content\n")], head=LATER_HEAD)

    db.expire_all()
    wf = db.exec(select(WorkflowFile).where(WorkflowFile.repo_id == repo.id)).one()
    # Stamp the row as written by a sync that resolved after the one below.
    wf.fetched_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    db.add(wf)
    db.commit()

    result = _sync(db, repo, [_file(path, "old content\n")], head=HEAD)

    assert result.skipped_stale == [path]
    db.refresh(wf)
    assert wf.raw_content == "new content\n"
    assert wf.source_commit_sha == LATER_HEAD
    # The caller is handed the newer content, not the older read, so a losing
    # run cannot push staleness back out as issues.
    assert result.contents[path] == "new content\n"


def test_losing_the_write_race_suppresses_deletion_reconciliation(
    db: Session, repo: Repository
) -> None:
    """A newer sync owns which paths are missing, not this one."""
    kept = ".github/workflows/kept.yml"
    other = ".github/workflows/other.yml"
    _sync(db, repo, [_file(kept, "a\n"), _file(other, "b\n")])

    db.expire_all()
    rows = {
        wf.path: wf
        for wf in db.exec(
            select(WorkflowFile).where(WorkflowFile.repo_id == repo.id)
        ).all()
    }
    rows[kept].fetched_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    db.add(rows[kept])
    db.commit()

    # Our older listing no longer mentions `other`, but our write lost the race.
    result = _sync(db, repo, [_file(kept, "a\n")], head=HEAD)

    assert result.skipped_stale == [kept]
    assert result.deleted == []
    db.refresh(rows[other])
    assert rows[other].deleted_at is None


# ─── Failure modes ───────────────────────────────────────────────────────────


def test_unresolvable_ref_with_an_empty_listing_reconciles_nothing(
    db: Session, repo: Repository
) -> None:
    """GitHub 404s the same way for "no workflows" and "no such branch"."""
    path = ".github/workflows/ci.yml"
    _sync(db, repo, [_file(path, "on: push\n")])

    result = _sync(db, repo, [], head=None)

    assert result.ref_unresolved is True
    assert result.deleted == []
    db.expire_all()
    wf = db.exec(select(WorkflowFile).where(WorkflowFile.repo_id == repo.id)).one()
    assert wf.deleted_at is None


def test_an_empty_listing_at_a_resolved_ref_is_believed(
    db: Session, repo: Repository
) -> None:
    """Once the ref resolves, an empty directory really is empty."""
    path = ".github/workflows/ci.yml"
    _sync(db, repo, [_file(path, "on: push\n")])

    result = _sync(db, repo, [], head=LATER_HEAD)

    assert result.ref_unresolved is False
    assert result.deleted == [path]


def test_a_failing_fetch_raises_workflow_fetch_error(
    db: Session, repo: Repository
) -> None:
    def boom(_repo: Repository, _ref: str | None) -> list[WorkflowFileContent]:
        raise RuntimeError("rate limited")

    with pytest.raises(WorkflowFetchError):
        sync_workflow_files(
            db,
            repo,
            repo.default_branch,
            fetch=boom,
            resolve_sha=lambda _r, _b: HEAD,
        )


def test_module_level_functions_are_the_default_seam(
    db: Session, repo: Repository
) -> None:
    """Callers that pass nothing still get patchable behaviour."""
    path = ".github/workflows/ci.yml"
    with (
        patch("app.services.workflow_sync.resolve_branch_head", return_value=HEAD),
        patch(
            "app.services.workflow_sync.fetch_workflow_files_for_repo",
            return_value=[_file(path, "on: push\n")],
        ),
    ):
        result = sync_workflow_files(db, repo, repo.default_branch)

    assert result.added == [path]
    assert result.head_sha == HEAD
