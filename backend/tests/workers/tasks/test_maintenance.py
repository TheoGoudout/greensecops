"""Unit tests for the maintenance sweeper task."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlmodel import Session

from app.models import (
    Category,
    DynamicAnalysisStatus,
    FixStatus,
    LLMProvider,
    Organization,
    PullRequest,
    PullRequestState,
    Repository,
    Rule,
    ScanFailureKind,
    ScanStatus,
    Severity,
    TelemetryRun,
    UserTier,
    WorkflowFile,
    WorkflowFinding,
    WorkflowFix,
    WorkflowScan,
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


def _build_chain(db: Session) -> tuple[WorkflowScan, WorkflowFix]:
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
    analysis = WorkflowScan(
        repo_id=repo.id,
        workflow_file_id=wf.id,
        content_hash=wf.content_hash,
        status=ScanStatus.running,
        created_at=old,
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)

    rule = Rule(
        slug=f"maint_rule_{uuid.uuid4().hex[:8]}",
        category=Category.energy,
        severity=Severity.low,
        title="t",
        description="d",
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)

    issue = WorkflowFinding(
        analysis_id=analysis.id,
        workflow_file_id=wf.id,
        rule_id=rule.id,
        fingerprint=uuid.uuid4().hex[:16],
        severity=Severity.low,
        category=Category.energy,
        message="m",
    )
    db.add(issue)
    db.commit()
    db.refresh(issue)

    fix = WorkflowFix(
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
    assert analysis.status == ScanStatus.failed
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
    assert analysis.status == ScanStatus.running
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


def test_sweeper_task_wrapper_runs(db: Session) -> None:
    from app.workers.tasks.maintenance import sweep_stuck_states

    result = sweep_stuck_states.apply()
    assert "swept_analyses" in result.get()


# ─── refresh_pr_mergeable_state ──────────────────────────────────────────────


def test_refresh_pr_mergeable_state_updates_attribute_and_emits(
    db: Session,
) -> None:
    from unittest.mock import patch

    from app.workers.tasks.maintenance import _refresh_pr_mergeable_state_impl

    analysis, fix = _build_chain(db)
    repo = db.get(Repository, analysis.repo_id)
    assert repo is not None
    pr = PullRequest(
        repo_id=repo.id,
        pr_branch=f"greensecops/maint-{uuid.uuid4().hex[:8]}",
        pr_url=f"https://github.com/{repo.full_name}/pull/21",
        pr_state=PullRequestState.open,
        mergeable_state="clean",
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)
    fix.pr_id = pr.id
    db.add(fix)
    db.commit()

    events: list = []
    with (
        patch(
            "app.workers.tasks.maintenance._fetch_pr_mergeable_state",
            return_value="dirty",
        ),
        patch(
            "app.workers.tasks.maintenance.events_pub.publish_event",
            side_effect=events.append,
        ),
    ):
        result = _refresh_pr_mergeable_state_impl(str(repo.id))

    assert result["updated"] == 1
    db.refresh(pr)
    assert pr.mergeable_state == "dirty"
    assert len(events) == 1


def test_refresh_pr_mergeable_state_skips_unchanged_and_no_installation(
    db: Session,
) -> None:
    from unittest.mock import patch

    from app.workers.tasks.maintenance import _refresh_pr_mergeable_state_impl

    analysis, _fix = _build_chain(db)
    repo = db.get(Repository, analysis.repo_id)
    assert repo is not None
    pr = PullRequest(
        repo_id=repo.id,
        pr_branch=f"greensecops/maint-{uuid.uuid4().hex[:8]}",
        pr_url=f"https://github.com/{repo.full_name}/pull/22",
        pr_state=PullRequestState.open,
        mergeable_state="clean",
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)

    # Unchanged state: no update, no event.
    events: list = []
    with (
        patch(
            "app.workers.tasks.maintenance._fetch_pr_mergeable_state",
            return_value="clean",
        ),
        patch(
            "app.workers.tasks.maintenance.events_pub.publish_event",
            side_effect=events.append,
        ),
    ):
        result = _refresh_pr_mergeable_state_impl(str(repo.id))
    assert result == {"checked": 1, "updated": 0}
    assert events == []

    # No installation: nothing checked at all.
    repo.installation_id = None
    db.add(repo)
    db.commit()
    result = _refresh_pr_mergeable_state_impl(str(repo.id))
    assert result == {"checked": 0, "updated": 0}


# ─── retry_transient_analyses ────────────────────────────────────────────────


def _failed_analysis(
    db: Session,
    repo: Repository,
    wf: WorkflowFile,
    kind: ScanFailureKind,
    completed_at: datetime | None = None,
) -> WorkflowScan:
    a = WorkflowScan(
        repo_id=repo.id,
        workflow_file_id=wf.id,
        content_hash=wf.content_hash,
        status=ScanStatus.failed,
        failure_kind=kind,
        branch="main",
        completed_at=completed_at or datetime.now(timezone.utc),
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def test_retry_transient_analyses_schedules_rerun(db: Session) -> None:
    from unittest.mock import patch

    from app.workers.tasks.maintenance import _retry_transient_analyses_impl

    analysis, _fix = _build_chain(db)
    repo = db.get(Repository, analysis.repo_id)
    assert repo is not None
    repo.enabled = True
    db.add(repo)
    db.commit()
    wf = db.get(WorkflowFile, analysis.workflow_file_id)
    assert wf is not None
    _failed_analysis(db, repo, wf, ScanFailureKind.transient)

    with (
        patch(
            "app.workers.tasks.static_analysis.run_static_analysis.delay"
        ) as mock_delay,
        patch(
            "app.workers.tasks.maintenance._try_acquire_auto_retry_slot",
            return_value=True,
        ),
    ):
        result = _retry_transient_analyses_impl()

    # The impl scans the whole (shared) test DB; assert on our repo's call.
    assert result["scheduled"] >= 1
    our_calls = [
        c.kwargs
        for c in mock_delay.call_args_list
        if c.kwargs["repo_id"] == str(repo.id)
    ]
    assert len(our_calls) == 1
    assert our_calls[0]["branch"] == "main"
    assert our_calls[0]["force"] is True


def test_retry_transient_analyses_skips_permanent_old_and_exhausted(
    db: Session,
) -> None:
    from unittest.mock import patch

    from app.workers.tasks.maintenance import (
        MAX_AUTO_RETRY_ATTEMPTS,
        _retry_transient_analyses_impl,
    )

    analysis, _fix = _build_chain(db)
    repo = db.get(Repository, analysis.repo_id)
    assert repo is not None
    repo.enabled = True
    db.add(repo)
    db.commit()
    wf = db.get(WorkflowFile, analysis.workflow_file_id)
    assert wf is not None

    # Permanent failure: never retried.
    _failed_analysis(db, repo, wf, ScanFailureKind.permanent)
    # Transient but too old: outside the window.
    _failed_analysis(
        db,
        repo,
        wf,
        ScanFailureKind.transient,
        completed_at=datetime.now(timezone.utc) - timedelta(hours=48),
    )

    with (
        patch(
            "app.workers.tasks.static_analysis.run_static_analysis.delay"
        ) as mock_delay,
        patch(
            "app.workers.tasks.maintenance._try_acquire_auto_retry_slot",
            return_value=True,
        ),
    ):
        _retry_transient_analyses_impl()
    assert not any(
        c.kwargs["repo_id"] == str(repo.id) for c in mock_delay.call_args_list
    )

    # Exhausted: MAX_AUTO_RETRY_ATTEMPTS recent transient failures for the
    # same content hash stop further retries.
    for _ in range(MAX_AUTO_RETRY_ATTEMPTS):
        _failed_analysis(db, repo, wf, ScanFailureKind.transient)
    with (
        patch(
            "app.workers.tasks.static_analysis.run_static_analysis.delay"
        ) as mock_delay,
        patch(
            "app.workers.tasks.maintenance._try_acquire_auto_retry_slot",
            return_value=True,
        ),
    ):
        result = _retry_transient_analyses_impl()
    assert result["skipped_exhausted"] >= 1
    assert not any(
        c.kwargs["repo_id"] == str(repo.id) for c in mock_delay.call_args_list
    )
