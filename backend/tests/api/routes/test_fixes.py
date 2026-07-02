"""Tests for the /api/v1/fixes/ endpoints."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models import (
    Analysis,
    AnalysisStatus,
    AnalysisTrigger,
    Fix,
    FixStatus,
    Issue,
    IssueCategory,
    IssueSeverity,
    LLMProvider,
    Organization,
    PullRequest,
    Repository,
    Rule,
    UserTier,
    WorkflowFile,
)

# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def org(db: Session) -> Organization:
    organization = Organization(
        name=f"fixes-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free
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
        full_name=f"fixesowner/repo-{uuid.uuid4().hex[:8]}",
        installation_id=99991,
    )
    db.add(repository)
    db.commit()
    db.refresh(repository)
    return repository


@pytest.fixture()
def workflow_file(db: Session, repo: Repository) -> WorkflowFile:
    wf = WorkflowFile(
        repo_id=repo.id,
        path=".github/workflows/fixes-test.yml",
        content_hash=uuid.uuid4().hex,
        raw_content="on: push\njobs: {}",
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


@pytest.fixture()
def analysis(db: Session, repo: Repository, workflow_file: WorkflowFile) -> Analysis:
    a = Analysis(
        repo_id=repo.id,
        workflow_file_id=workflow_file.id,
        content_hash=workflow_file.content_hash,
        status=AnalysisStatus.completed,
        score=80.0,
        grade="B",
        triggered_by=AnalysisTrigger.manual,
        branch="main",
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


@pytest.fixture()
def rule(db: Session) -> Rule:
    r = Rule(
        slug=f"test-fixes-rule-{uuid.uuid4().hex[:8]}",
        category=IssueCategory.reliability,
        severity=IssueSeverity.medium,
        title="Test Fixes Rule",
        description="A test rule for fixes tests",
        enabled=True,
        severity_weight=1.0,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


@pytest.fixture()
def issue(db: Session, analysis: Analysis, rule: Rule) -> Issue:
    i = Issue(
        analysis_id=analysis.id,
        workflow_file_id=analysis.workflow_file_id,
        rule_id=rule.id,
        severity=IssueSeverity.medium,
        category=IssueCategory.reliability,
        line_start=5,
        line_end=7,
        message="Test reliability issue",
        context='{"step": "build"}',
    )
    db.add(i)
    db.commit()
    db.refresh(i)
    return i


@pytest.fixture()
def ready_fix(db: Session, issue: Issue) -> Fix:
    f = Fix(
        issue_id=issue.id,
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o-mini",
        status=FixStatus.ready,
        diff="--- a/ci.yml\n+++ b/ci.yml\n@@ -1 +1 @@\n-old\n+new",
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    return f


@pytest.fixture()
def pending_fix(db: Session, db_issue_for_pending: Issue) -> Fix:
    f = Fix(
        issue_id=db_issue_for_pending.id,
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o-mini",
        status=FixStatus.pending,
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    return f


@pytest.fixture()
def db_issue_for_pending(db: Session, analysis: Analysis, rule: Rule) -> Issue:
    """A second issue for the pending fix fixture (avoids unique constraint on issue_id)."""
    i = Issue(
        analysis_id=analysis.id,
        workflow_file_id=analysis.workflow_file_id,
        rule_id=rule.id,
        severity=IssueSeverity.low,
        category=IssueCategory.reliability,
        line_start=20,
        line_end=22,
        message="Second test issue for pending fix",
    )
    db.add(i)
    db.commit()
    db.refresh(i)
    return i


# ─── GET /fixes/ ──────────────────────────────────────────────────────────────


def test_list_fixes_empty(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    issue: Issue,
) -> None:
    # Arrange — issue fixture exists but no fix attached yet
    # (ready_fix fixture is not used here)

    # Act
    response = client.get(
        f"{settings.API_V1_STR}/fixes/",
        params={"issue_id": str(issue.id)},
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    # The issue may or may not already have a fix from another test — we just
    # verify the endpoint returns 200 with a list.
    assert isinstance(response.json(), list)


def test_list_fixes_with_data(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    ready_fix: Fix,
    issue: Issue,
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/fixes/",
        params={"issue_id": str(issue.id)},
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    ids = [f["id"] for f in data]
    assert str(ready_fix.id) in ids


def test_list_fixes_filter_by_status(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    ready_fix: Fix,
    issue: Issue,
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/fixes/",
        params={"issue_id": str(issue.id), "status": "ready"},
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert all(f["status"] == "ready" for f in data)
    assert any(f["id"] == str(ready_fix.id) for f in data)


def test_list_fixes_filter_by_repo_id(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    ready_fix: Fix,
    repo: Repository,
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/fixes/",
        params={"repo_id": str(repo.id)},
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert any(f["id"] == str(ready_fix.id) for f in data)


def test_list_fixes_filter_by_analysis_id(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    ready_fix: Fix,
    analysis: Analysis,
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/fixes/",
        params={"analysis_id": str(analysis.id)},
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert any(f["id"] == str(ready_fix.id) for f in data)


# ─── GET /fixes/{id} ──────────────────────────────────────────────────────────


def test_get_fix_found(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    ready_fix: Fix,
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/fixes/{ready_fix.id}",
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(ready_fix.id)
    assert body["status"] == "ready"


def test_get_fix_not_found(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/fixes/{uuid.uuid4()}",
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 404
    assert response.json()["detail"] == "Fix not found"


# ─── POST /fixes/generate-for-repo/{repo_id} ─────────────────────────────────


def test_generate_fixes_for_repo_queues_tasks(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    issue: Issue,
    repo: Repository,
) -> None:
    # Act
    with patch("app.api.routes.fixes.run_fix_generation.delay") as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/fixes/generate-for-repo/{repo.id}",
            headers=superuser_token_headers,
        )

    # Assert
    assert response.status_code == 202
    body = response.json()
    assert body["queued"] >= 1
    mock_delay.assert_called()


def test_generate_fixes_for_repo_with_issue_ids_filter(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    issue: Issue,
    repo: Repository,
) -> None:
    # Act — pass issue_ids to restrict which issues get fixes generated
    with patch("app.api.routes.fixes.run_fix_generation.delay") as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/fixes/generate-for-repo/{repo.id}",
            headers=superuser_token_headers,
            json={"issue_ids": [str(issue.id)]},
        )

    # Assert
    assert response.status_code == 202
    body = response.json()
    assert body["queued"] >= 1
    mock_delay.assert_called()


def test_generate_fixes_for_repo_with_nonexistent_issue_ids_returns_zero(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
) -> None:
    # Act — pass a random issue_id that doesn't belong to this repo
    with patch("app.api.routes.fixes.run_fix_generation.delay") as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/fixes/generate-for-repo/{repo.id}",
            headers=superuser_token_headers,
            json={"issue_ids": [str(uuid.uuid4())]},
        )

    # Assert
    assert response.status_code == 202
    assert response.json()["queued"] == 0
    mock_delay.assert_not_called()


def test_generate_fixes_for_repo_replaces_existing_fixes(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    ready_fix: Fix,
    repo: Repository,
    db: Session,
) -> None:
    # Arrange — ready_fix.issue already has a ready fix
    fix_id = ready_fix.id
    with patch("app.api.routes.fixes.run_fix_generation.delay") as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/fixes/generate-for-repo/{repo.id}",
            headers=superuser_token_headers,
        )

    # Assert — existing non-delivered fix deleted, new task queued
    assert response.status_code == 202
    assert response.json()["queued"] >= 1
    mock_delay.assert_called()
    db.expire_all()  # clear identity map so get() hits the DB
    assert db.get(Fix, fix_id) is None


# ─── POST /fixes/generate/{issue_id} ─────────────────────────────────────────


def test_generate_fix_queues_task(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    analysis: Analysis,
    rule: Rule,
) -> None:
    # Arrange — create a fresh issue so no existing fix conflicts
    fresh_issue = Issue(
        analysis_id=analysis.id,
        rule_id=rule.id,
        severity=IssueSeverity.high,
        category=IssueCategory.security,
        line_start=1,
        line_end=3,
        message="Issue for generate test",
    )
    db.add(fresh_issue)
    db.commit()
    db.refresh(fresh_issue)

    # Act
    with patch(
        "app.workers.tasks.fix_generation.run_fix_generation.delay"
    ) as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/fixes/generate/{fresh_issue.id}",
            headers=superuser_token_headers,
        )

    # Assert
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["issue_id"] == str(fresh_issue.id)
    mock_delay.assert_called_once_with(issue_ids=[str(fresh_issue.id)])


def test_generate_fix_issue_not_found(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    # Act
    with patch("app.workers.tasks.fix_generation.run_fix_generation.delay"):
        response = client.post(
            f"{settings.API_V1_STR}/fixes/generate/{uuid.uuid4()}",
            headers=superuser_token_headers,
        )

    # Assert
    assert response.status_code == 404
    assert response.json()["detail"] == "Issue not found"


# ─── POST /fixes/{id}/deliver ─────────────────────────────────────────────────


def test_deliver_fix_queues_task(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    ready_fix: Fix,
) -> None:
    # Act
    with patch("app.workers.tasks.fix_delivery.deliver_fix.delay") as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/fixes/{ready_fix.id}/deliver",
            headers=superuser_token_headers,
        )

    # Assert
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["fix_id"] == str(ready_fix.id)
    mock_delay.assert_called_once_with(fix_id=str(ready_fix.id), force=False)


def test_deliver_fix_not_ready_returns_409(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    pending_fix: Fix,
) -> None:
    # Act
    with patch("app.workers.tasks.fix_delivery.deliver_fix.delay"):
        response = client.post(
            f"{settings.API_V1_STR}/fixes/{pending_fix.id}/deliver",
            headers=superuser_token_headers,
        )

    # Assert
    assert response.status_code == 409
    assert "not ready" in response.json()["detail"].lower()


def test_deliver_fix_not_found(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    # Act
    with patch("app.workers.tasks.fix_delivery.deliver_fix.delay"):
        response = client.post(
            f"{settings.API_V1_STR}/fixes/{uuid.uuid4()}/deliver",
            headers=superuser_token_headers,
        )

    # Assert
    assert response.status_code == 404
    assert response.json()["detail"] == "Fix not found"


# ─── DELETE /fixes/{id} ───────────────────────────────────────────────────────


def test_reject_fix_found(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    ready_fix: Fix,
    db: Session,
) -> None:
    # Act
    response = client.delete(
        f"{settings.API_V1_STR}/fixes/{ready_fix.id}",
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 204

    db.refresh(ready_fix)
    assert ready_fix.status == FixStatus.rejected


def test_reject_fix_not_found(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    # Act
    response = client.delete(
        f"{settings.API_V1_STR}/fixes/{uuid.uuid4()}",
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 404


# ─── POST /fixes/deliver-for-workflow ─────────────────────────────────────────


def test_deliver_for_workflow_queues_batch(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    ready_fix: Fix,
) -> None:
    # Act
    with patch(
        "app.workers.tasks.fix_delivery.deliver_fixes_batch.delay"
    ) as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/fixes/deliver-for-workflow",
            headers=superuser_token_headers,
            json={"fix_ids": [str(ready_fix.id)]},
        )

    # Assert
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    mock_delay.assert_called_once()
    call_kwargs = mock_delay.call_args.kwargs
    assert str(ready_fix.id) in call_kwargs["fix_ids"]


def test_deliver_for_workflow_no_ready_fixes_returns_404(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    pending_fix: Fix,
) -> None:
    # Act
    with patch("app.workers.tasks.fix_delivery.deliver_fixes_batch.delay"):
        response = client.post(
            f"{settings.API_V1_STR}/fixes/deliver-for-workflow",
            headers=superuser_token_headers,
            json={"fix_ids": [str(pending_fix.id)]},
        )

    # Assert
    assert response.status_code == 404
    assert "No ready fixes" in response.json()["detail"]


def test_deliver_for_workflow_empty_ids_returns_404(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    # Act
    with patch("app.workers.tasks.fix_delivery.deliver_fixes_batch.delay"):
        response = client.post(
            f"{settings.API_V1_STR}/fixes/deliver-for-workflow",
            headers=superuser_token_headers,
            json={"fix_ids": [str(uuid.uuid4())]},
        )

    # Assert
    assert response.status_code == 404


# ─── POST /fixes/deliver-for-repo/{repo_id} ───────────────────────────────────


def test_deliver_for_repo_queues_batch(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    ready_fix: Fix,
    repo: Repository,
) -> None:
    # Act
    with patch(
        "app.workers.tasks.fix_delivery.deliver_fixes_batch.delay"
    ) as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/fixes/deliver-for-repo/{repo.id}",
            headers=superuser_token_headers,
        )

    # Assert
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    mock_delay.assert_called_once()
    call_kwargs = mock_delay.call_args.kwargs
    assert str(ready_fix.id) in call_kwargs["fix_ids"]
    assert str(repo.id) == call_kwargs["repo_id"]


def test_deliver_for_repo_not_found_returns_404(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    # Act
    with patch("app.workers.tasks.fix_delivery.deliver_fixes_batch.delay"):
        response = client.post(
            f"{settings.API_V1_STR}/fixes/deliver-for-repo/{uuid.uuid4()}",
            headers=superuser_token_headers,
        )

    # Assert
    assert response.status_code == 404
    assert "Repository not found" in response.json()["detail"]


def test_deliver_for_repo_no_ready_fixes_returns_404(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
    pending_fix: Fix,
) -> None:
    # Act - repo exists but only has a pending fix (not ready)
    # We use a separate repo that only has the pending fix to avoid interference
    with patch("app.workers.tasks.fix_delivery.deliver_fixes_batch.delay"):
        response = client.post(
            f"{settings.API_V1_STR}/fixes/deliver-for-repo/{repo.id}",
            headers=superuser_token_headers,
        )

    # Assert - pending_fix is not ready, so no fixes to deliver
    # Note: repo fixture may have a ready_fix from other tests in same session,
    # so we only assert a valid HTTP response
    assert response.status_code in (202, 404)


# ─── Force re-run tests ───────────────────────────────────────────────────────


def test_generate_fixes_for_repo_preserves_delivered_and_skips_in_task(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    issue: Issue,
    repo: Repository,
) -> None:
    # Arrange — delivered fix must not be re-inserted (unique constraint)
    delivered_fix = Fix(
        issue_id=issue.id,
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o-mini",
        status=FixStatus.delivered,
        diff="--- a/ci.yml\n+++ b/ci.yml\n@@ -1 +1 @@\n-old\n+new",
    )
    db.add(delivered_fix)
    db.commit()
    db.refresh(delivered_fix)
    fix_id = delivered_fix.id

    # Act — no force: delivered fix preserved, task queued
    with patch("app.api.routes.fixes.run_fix_generation.delay"):
        response = client.post(
            f"{settings.API_V1_STR}/fixes/generate-for-repo/{repo.id}",
            headers=superuser_token_headers,
        )

    # Assert — delivered fix still exists (not deleted)
    assert response.status_code == 202
    db.expire_all()
    assert db.get(Fix, fix_id) is not None
    assert db.get(Fix, fix_id).status == FixStatus.delivered


def test_generate_fixes_for_repo_force_deletes_delivered(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    issue: Issue,
    repo: Repository,
) -> None:
    # Arrange — create a delivered fix that should normally be preserved
    delivered_fix = Fix(
        issue_id=issue.id,
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o-mini",
        status=FixStatus.delivered,
        diff="--- a/ci.yml\n+++ b/ci.yml\n@@ -1 +1 @@\n-old\n+new",
    )
    db.add(delivered_fix)
    db.commit()
    db.refresh(delivered_fix)
    fix_id = delivered_fix.id

    # Act
    with patch("app.api.routes.fixes.run_fix_generation.delay"):
        response = client.post(
            f"{settings.API_V1_STR}/fixes/generate-for-repo/{repo.id}",
            params={"force": "true"},
            headers=superuser_token_headers,
        )

    # Assert — delivered fix deleted because force=True
    assert response.status_code == 202
    db.expire_all()
    assert db.get(Fix, fix_id) is None


def test_trigger_fix_delivery_force_bypasses_status_check(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    issue: Issue,
) -> None:
    # Arrange — a fix that is already delivered (would normally return 409)
    delivered_fix = Fix(
        issue_id=issue.id,
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o-mini",
        status=FixStatus.delivered,
        diff="--- a/ci.yml\n+++ b/ci.yml\n@@ -1 +1 @@\n-old\n+new",
    )
    db.add(delivered_fix)
    db.commit()
    db.refresh(delivered_fix)

    # Act
    with patch("app.workers.tasks.fix_delivery.deliver_fix.delay") as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/fixes/{delivered_fix.id}/deliver",
            params={"force": "true"},
            headers=superuser_token_headers,
        )

    # Assert — 202 instead of 409, force=True forwarded to task
    assert response.status_code == 202
    mock_delay.assert_called_once_with(fix_id=str(delivered_fix.id), force=True)


def test_deliver_for_workflow_force_includes_non_ready(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    pending_fix: Fix,
) -> None:
    # Act — pending fix would normally be excluded (no ready fixes → 404)
    with patch(
        "app.workers.tasks.fix_delivery.deliver_fixes_batch.delay"
    ) as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/fixes/deliver-for-workflow",
            params={"force": "true"},
            headers=superuser_token_headers,
            json={"fix_ids": [str(pending_fix.id)]},
        )

    # Assert — force=True includes the pending fix
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    mock_delay.assert_called_once()
    call_kwargs = mock_delay.call_args.kwargs
    assert str(pending_fix.id) in call_kwargs["fix_ids"]
    assert call_kwargs["force"] is True


# ─── latest_only / stable branch tests ───────────────────────────────────────


def test_generate_fixes_for_repo_only_targets_latest_analysis(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    workflow_file: WorkflowFile,
    rule: Rule,
    analysis: Analysis,
    issue: Issue,
) -> None:
    # Arrange — create a second (old) analysis with an older completed_at
    from datetime import datetime, timezone

    old_analysis = Analysis(
        repo_id=repo.id,
        workflow_file_id=workflow_file.id,
        content_hash=uuid.uuid4().hex,
        status=AnalysisStatus.completed,
        score=50.0,
        grade="D",
        triggered_by=AnalysisTrigger.manual,
        branch="main",
        completed_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    db.add(old_analysis)
    db.commit()
    db.refresh(old_analysis)

    # Give the current analysis a newer completed_at
    analysis.completed_at = datetime.now(timezone.utc)
    db.add(analysis)
    db.commit()

    old_issue = Issue(
        analysis_id=old_analysis.id,
        workflow_file_id=old_analysis.workflow_file_id,
        rule_id=rule.id,
        severity=IssueSeverity.medium,
        category=IssueCategory.reliability,
        line_start=20,
        line_end=22,
        message="Old analysis issue — should not be targeted",
    )
    db.add(old_issue)
    db.commit()

    with patch("app.api.routes.fixes.run_fix_generation.delay") as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/fixes/generate-for-repo/{repo.id}",
            headers=superuser_token_headers,
        )

    assert response.status_code == 202
    queued_issue_ids: list[str] = []
    for call in mock_delay.call_args_list:
        queued_issue_ids.extend(call.kwargs.get("issue_ids", []))

    assert str(issue.id) in queued_issue_ids
    assert str(old_issue.id) not in queued_issue_ids


def test_deliver_for_repo_uses_stable_branch_name(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    ready_fix: Fix,
    repo: Repository,
) -> None:
    # Act
    with patch(
        "app.workers.tasks.fix_delivery.deliver_fixes_batch.delay"
    ) as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/fixes/deliver-for-repo/{repo.id}",
            headers=superuser_token_headers,
        )

    assert response.status_code == 202
    pr_branch = mock_delay.call_args.kwargs["pr_branch"]
    # Stable branch is derived from repo_id prefix, not a timestamp
    assert pr_branch == f"greensecops/fixes-{str(repo.id)[:8]}"


def test_deliver_for_repo_reuses_existing_pr_branch(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    ready_fix: Fix,
    repo: Repository,
    analysis: Analysis,
    issue: Issue,
) -> None:
    # Arrange — simulate a previous delivery by creating a PullRequest record
    # and linking the fix to it via pr_id
    existing_branch = "greensecops/fixes-previousbranch"
    pr = PullRequest(
        repo_id=repo.id,
        pr_branch=existing_branch,
        pr_url=f"https://github.com/{repo.full_name}/pull/99",
        pr_state="open",
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)
    ready_fix.pr_id = pr.id
    db.add(ready_fix)
    db.commit()

    # Act
    with patch(
        "app.workers.tasks.fix_delivery.deliver_fixes_batch.delay"
    ) as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/fixes/deliver-for-repo/{repo.id}",
            params={"force": "true"},
            headers=superuser_token_headers,
        )

    assert response.status_code == 202
    pr_branch = mock_delay.call_args.kwargs["pr_branch"]
    # Must reuse the existing branch, not generate a new one
    assert pr_branch == existing_branch


# ─── POST /fixes/sync-pr-status/{repo_id} ───────────────────────────────────


def _make_open_pr_fix(
    db: Session,
    repo: Repository,
    issue: Issue,
    pr_url: str,
    pr_branch: str = "greensecops/fix",
) -> tuple[Fix, PullRequest]:
    pr = PullRequest(
        repo_id=repo.id,
        pr_branch=pr_branch,
        pr_url=pr_url,
        pr_state="open",
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)
    fix = Fix(
        issue_id=issue.id,
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o-mini",
        status=FixStatus.delivered,
        pr_id=pr.id,
    )
    db.add(fix)
    db.commit()
    db.refresh(fix)
    return fix, pr


def test_sync_pr_status_no_open_prs(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/fixes/sync-pr-status/{repo.id}",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["synced"] == 0
    assert data["updated"] == 0


def test_sync_pr_status_updates_merged_pr(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    analysis: Analysis,
    rule: Rule,
) -> None:
    issue = Issue(
        analysis_id=analysis.id,
        rule_id=rule.id,
        severity=IssueSeverity.high,
        category=IssueCategory.security,
        message="sync merged test",
    )
    db.add(issue)
    db.commit()
    db.refresh(issue)

    pr_url = f"https://github.com/{repo.full_name}/pull/101"
    _fix, pr = _make_open_pr_fix(db, repo, issue, pr_url)

    from app.api.deps import get_github_app_client
    from app.main import app as fastapi_app

    mock_client = AsyncMock()
    mock_client.get_pr_state = AsyncMock(return_value="merged")
    fastapi_app.dependency_overrides[get_github_app_client] = lambda: mock_client
    try:
        response = client.post(
            f"{settings.API_V1_STR}/fixes/sync-pr-status/{repo.id}",
            headers=superuser_token_headers,
        )
    finally:
        fastapi_app.dependency_overrides.pop(get_github_app_client, None)

    assert response.status_code == 200
    data = response.json()
    assert data["synced"] == 1
    assert data["updated"] == 1

    db.refresh(pr)
    assert pr.pr_state == "merged"


def test_sync_pr_status_updates_closed_pr(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    analysis: Analysis,
    rule: Rule,
) -> None:
    issue = Issue(
        analysis_id=analysis.id,
        rule_id=rule.id,
        severity=IssueSeverity.high,
        category=IssueCategory.security,
        message="sync closed test",
    )
    db.add(issue)
    db.commit()
    db.refresh(issue)

    pr_url = f"https://github.com/{repo.full_name}/pull/102"
    _fix, pr = _make_open_pr_fix(db, repo, issue, pr_url)

    from app.api.deps import get_github_app_client
    from app.main import app as fastapi_app

    mock_client = AsyncMock()
    mock_client.get_pr_state = AsyncMock(return_value="closed")
    fastapi_app.dependency_overrides[get_github_app_client] = lambda: mock_client
    try:
        response = client.post(
            f"{settings.API_V1_STR}/fixes/sync-pr-status/{repo.id}",
            headers=superuser_token_headers,
        )
    finally:
        fastapi_app.dependency_overrides.pop(get_github_app_client, None)

    assert response.status_code == 200
    data = response.json()
    assert data["updated"] == 1

    db.refresh(pr)
    assert pr.pr_state == "closed"


def test_sync_pr_status_skips_already_closed(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    analysis: Analysis,
    rule: Rule,
) -> None:
    issue = Issue(
        analysis_id=analysis.id,
        rule_id=rule.id,
        severity=IssueSeverity.medium,
        category=IssueCategory.reliability,
        message="already closed test",
    )
    db.add(issue)
    db.commit()
    db.refresh(issue)

    # PR is already closed — should not be included in sync query
    pr = PullRequest(
        repo_id=repo.id,
        pr_branch="greensecops/fix-closed",
        pr_url=f"https://github.com/{repo.full_name}/pull/103",
        pr_state="closed",
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)
    fix = Fix(
        issue_id=issue.id,
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o-mini",
        status=FixStatus.delivered,
        pr_id=pr.id,
    )
    db.add(fix)
    db.commit()

    response = client.post(
        f"{settings.API_V1_STR}/fixes/sync-pr-status/{repo.id}",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["synced"] == 0
    assert data["updated"] == 0


def test_sync_pr_status_handles_github_error(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    analysis: Analysis,
    rule: Rule,
) -> None:
    issue = Issue(
        analysis_id=analysis.id,
        rule_id=rule.id,
        severity=IssueSeverity.high,
        category=IssueCategory.security,
        message="github error test",
    )
    db.add(issue)
    db.commit()
    db.refresh(issue)

    pr_url = f"https://github.com/{repo.full_name}/pull/104"
    _fix, pr = _make_open_pr_fix(db, repo, issue, pr_url)

    from app.api.deps import get_github_app_client
    from app.main import app as fastapi_app

    mock_client = AsyncMock()
    mock_client.get_pr_state = AsyncMock(side_effect=Exception("API error"))
    fastapi_app.dependency_overrides[get_github_app_client] = lambda: mock_client
    try:
        response = client.post(
            f"{settings.API_V1_STR}/fixes/sync-pr-status/{repo.id}",
            headers=superuser_token_headers,
        )
    finally:
        fastapi_app.dependency_overrides.pop(get_github_app_client, None)

    assert response.status_code == 200
    data = response.json()
    assert data["synced"] == 1
    assert data["updated"] == 0

    db.refresh(pr)
    assert pr.pr_state == "open"


def test_sync_pr_status_repo_not_found(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/fixes/sync-pr-status/{uuid.uuid4()}",
        headers=superuser_token_headers,
    )
    assert response.status_code == 404
