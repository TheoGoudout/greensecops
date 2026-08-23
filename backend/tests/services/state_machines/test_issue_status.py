"""DB-backed tests for the trigger-maintained Issue.status column (migration 0022)."""

import uuid
from datetime import datetime, timezone

import pytest
from sqlmodel import Session, select

from app.models import (
    Analysis,
    AnalysisStatus,
    Category,
    Fix,
    FixStatus,
    Issue,
    IssueStatus,
    LLMProvider,
    Organization,
    Repository,
    Rule,
    Severity,
    WorkflowFile,
)


@pytest.fixture()
def issue_ctx(db: Session):
    org = Organization(name=f"iss-{uuid.uuid4().hex[:8]}")
    db.add(org)
    db.flush()
    repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"o/r-{uuid.uuid4().hex[:8]}",
    )
    db.add(repo)
    db.flush()
    wf = WorkflowFile(
        repo_id=repo.id,
        path=".github/workflows/x.yml",
        content_hash=uuid.uuid4().hex,
        raw_content="x",
    )
    db.add(wf)
    db.flush()
    analysis = Analysis(
        repo_id=repo.id,
        workflow_file_id=wf.id,
        content_hash="h",
        status=AnalysisStatus.completed,
    )
    db.add(analysis)
    db.flush()
    rule = db.exec(select(Rule)).first()
    assert rule is not None
    issue = Issue(
        analysis_id=analysis.id,
        workflow_file_id=wf.id,
        rule_id=rule.id,
        severity=Severity.high,
        category=Category.security,
        message="m",
        fingerprint=uuid.uuid4().hex[:16],
    )
    db.add(issue)
    db.commit()
    db.refresh(issue)
    return db, wf, issue


def test_new_issue_is_open(issue_ctx) -> None:
    _, _, issue = issue_ctx
    assert issue.status is IssueStatus.open


def test_linking_a_fix_sets_fix_in_progress(issue_ctx) -> None:
    db, wf, issue = issue_ctx
    fix = Fix(
        workflow_file_id=wf.id,
        llm_provider=LLMProvider.openai,
        llm_model="m",
        status=FixStatus.pending,
    )
    db.add(fix)
    db.flush()
    issue.fix_id = fix.id
    db.add(issue)
    db.commit()
    db.refresh(issue)
    assert issue.status is IssueStatus.fix_in_progress


def test_deleting_the_fix_reverts_to_open_via_cascade(issue_ctx) -> None:
    db, wf, issue = issue_ctx
    fix = Fix(
        workflow_file_id=wf.id,
        llm_provider=LLMProvider.openai,
        llm_model="m",
        status=FixStatus.pending,
    )
    db.add(fix)
    db.flush()
    issue.fix_id = fix.id
    db.add(issue)
    db.commit()

    # ON DELETE SET NULL clears fix_id without touching app code; the trigger
    # must still revert status to open.
    db.delete(fix)
    db.commit()
    db.refresh(issue)
    assert issue.fix_id is None
    assert issue.status is IssueStatus.open


def test_resolving_wins_over_fix_link(issue_ctx) -> None:
    db, wf, issue = issue_ctx
    fix = Fix(
        workflow_file_id=wf.id,
        llm_provider=LLMProvider.openai,
        llm_model="m",
        status=FixStatus.pending,
    )
    db.add(fix)
    db.flush()
    issue.fix_id = fix.id
    issue.resolved_at = datetime.now(timezone.utc)
    db.add(issue)
    db.commit()
    db.refresh(issue)
    assert issue.status is IssueStatus.resolved


def test_ignoring_sets_ignored(issue_ctx) -> None:
    db, _, issue = issue_ctx
    issue.ignored_at = datetime.now(timezone.utc)
    db.add(issue)
    db.commit()
    db.refresh(issue)
    assert issue.status is IssueStatus.ignored


def test_ignored_wins_over_resolved_and_fix(issue_ctx) -> None:
    # ``ignored_at`` takes precedence over both resolved_at and a fix link.
    db, wf, issue = issue_ctx
    fix = Fix(
        workflow_file_id=wf.id,
        llm_provider=LLMProvider.openai,
        llm_model="m",
        status=FixStatus.pending,
    )
    db.add(fix)
    db.flush()
    issue.fix_id = fix.id
    issue.resolved_at = datetime.now(timezone.utc)
    issue.ignored_at = datetime.now(timezone.utc)
    db.add(issue)
    db.commit()
    db.refresh(issue)
    assert issue.status is IssueStatus.ignored


def test_unignoring_falls_back_to_underlying_state(issue_ctx) -> None:
    db, _, issue = issue_ctx
    issue.ignored_at = datetime.now(timezone.utc)
    db.add(issue)
    db.commit()
    db.refresh(issue)
    assert issue.status is IssueStatus.ignored
    # Clearing ignored_at reverts to the resolved_at/fix_id-derived state.
    issue.ignored_at = None
    db.add(issue)
    db.commit()
    db.refresh(issue)
    assert issue.status is IssueStatus.open
