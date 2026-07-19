"""Unit tests for the maintenance sweeper task."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlmodel import Session

from app.models import (
    Analysis,
    AnalysisStatus,
    DynamicAnalysisStatus,
    Fix,
    FixStatus,
    Issue,
    IssueCategory,
    IssueSeverity,
    LLMProvider,
    Organization,
    Repository,
    Rule,
    TelemetryRun,
    UserTier,
    WorkflowFile,
)
from app.workers.tasks.maintenance import _sweep_stuck_states_impl


def _build_telemetry_run(
    db: Session, status: DynamicAnalysisStatus, *, stale: bool
) -> TelemetryRun:
    org = Organization(name=f"maint-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free)
    db.add(org)
    db.commit()
    db.refresh(org)

    repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"maint/repo-{uuid.uuid4().hex[:8]}",
        installation_id=40001,
        default_branch="main",
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    collected_at = datetime.now(timezone.utc) - (
        timedelta(hours=2) if stale else timedelta(minutes=1)
    )
    run = TelemetryRun(
        repo_id=repo.id,
        workflow_run_id=1,
        dynamic_status=status,
        collected_at=collected_at,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _build_chain(db: Session) -> tuple[Analysis, Fix]:
    org = Organization(name=f"maint-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free)
    db.add(org)
    db.commit()
    db.refresh(org)

    repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"maint/repo-{uuid.uuid4().hex[:8]}",
        installation_id=40001,
        default_branch="main",
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    wf = WorkflowFile(
        repo_id=repo.id,
        path=".github/workflows/maint.yml",
        content_hash=uuid.uuid4().hex,
        raw_content="on: push\n",
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)

    old = datetime.now(timezone.utc) - timedelta(hours=2)
    analysis = Analysis(
        repo_id=repo.id,
        workflow_file_id=wf.id,
        content_hash=wf.content_hash,
        status=AnalysisStatus.running,
        created_at=old,
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)

    rule = Rule(
        slug=f"maint_rule_{uuid.uuid4().hex[:8]}",
        category=IssueCategory.energy,
        severity=IssueSeverity.low,
        title="t",
        description="d",
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)

    issue = Issue(
        analysis_id=analysis.id,
        workflow_file_id=wf.id,
        rule_id=rule.id,
        fingerprint=uuid.uuid4().hex[:16],
        severity=IssueSeverity.low,
        category=IssueCategory.energy,
        message="m",
    )
    db.add(issue)
    db.commit()
    db.refresh(issue)

    fix = Fix(
        workflow_file_id=wf.id,
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o-mini",
        status=FixStatus.generating,
        created_at=old,
    )
    db.add(fix)
    db.commit()
    db.refresh(fix)

    return analysis, fix


def test_sweeper_fails_stuck_analysis_and_fix(db: Session) -> None:
    analysis, fix = _build_chain(db)

    result = _sweep_stuck_states_impl()

    assert result["swept_analyses"] >= 1
    assert result["swept_fixes"] >= 1
    db.refresh(analysis)
    db.refresh(fix)
    assert analysis.status == AnalysisStatus.failed
    assert "Timed out" in (analysis.error_message or "")
    assert analysis.completed_at is not None
    assert fix.status == FixStatus.failed
    assert "Timed out" in (fix.error_message or "")


def test_sweeper_leaves_recent_records_alone(db: Session) -> None:
    analysis, fix = _build_chain(db)
    # Make them fresh
    analysis.created_at = datetime.now(timezone.utc)
    fix.created_at = datetime.now(timezone.utc)
    db.add(analysis)
    db.add(fix)
    db.commit()

    _sweep_stuck_states_impl()

    db.refresh(analysis)
    db.refresh(fix)
    assert analysis.status == AnalysisStatus.running
    assert fix.status == FixStatus.generating


def test_sweeper_fails_stuck_telemetry_runs(db: Session) -> None:
    queued_run = _build_telemetry_run(db, DynamicAnalysisStatus.queued, stale=True)
    running_run = _build_telemetry_run(db, DynamicAnalysisStatus.running, stale=True)

    result = _sweep_stuck_states_impl()

    assert result["swept_telemetry"] >= 2
    db.refresh(queued_run)
    db.refresh(running_run)
    assert queued_run.dynamic_status == DynamicAnalysisStatus.failed
    assert running_run.dynamic_status == DynamicAnalysisStatus.failed


def test_sweeper_leaves_recent_telemetry_runs_alone(db: Session) -> None:
    run = _build_telemetry_run(db, DynamicAnalysisStatus.running, stale=False)

    _sweep_stuck_states_impl()

    db.refresh(run)
    assert run.dynamic_status == DynamicAnalysisStatus.running


def test_sweeper_task_wrapper_runs(db: Session) -> None:  # noqa: ARG001
    from app.workers.tasks.maintenance import sweep_stuck_states

    result = sweep_stuck_states.apply()
    assert "swept_analyses" in result.get()
