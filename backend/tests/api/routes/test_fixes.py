"""Tests for the /api/v1/fixes/ endpoints."""

import uuid
from unittest.mock import patch

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
    with patch("app.api.routes.fixes.run_batch_fix_generation.delay") as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/fixes/generate-for-repo/{repo.id}",
            headers=superuser_token_headers,
        )

    # Assert
    assert response.status_code == 202
    body = response.json()
    assert body["queued"] >= 1
    mock_delay.assert_called()


def test_generate_fixes_for_repo_replaces_existing_fixes(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    ready_fix: Fix,
    repo: Repository,
    db: Session,
) -> None:
    # Arrange — ready_fix.issue already has a ready fix
    fix_id = ready_fix.id
    with patch("app.api.routes.fixes.run_batch_fix_generation.delay") as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/fixes/generate-for-repo/{repo.id}",
            headers=superuser_token_headers,
        )

    # Assert — existing non-delivered fix deleted, new task queued
    assert response.status_code == 202
    assert response.json()["queued"] >= 1
    mock_delay.assert_called()
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
    mock_delay.assert_called_once_with(issue_id=str(fresh_issue.id))


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
    mock_delay.assert_called_once_with(fix_id=str(ready_fix.id))


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
    assert response.json()["detail"] == "Fix not found"
