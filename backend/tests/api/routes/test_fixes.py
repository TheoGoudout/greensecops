"""Tests for the /api/v1/fixes/ endpoints."""

import uuid
from datetime import UTC, datetime
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
    OrgMember,
    PullRequest,
    Repository,
    Rule,
    UserTier,
    WorkflowFile,
)
from tests.utils.user import authentication_token_from_email, create_random_user

_FULL_CONTENT = "on: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n"

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
def ready_fix(db: Session, workflow_file: WorkflowFile, issue: Issue) -> Fix:
    f = Fix(
        workflow_file_id=workflow_file.id,
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o-mini",
        status=FixStatus.ready,
        full_content=_FULL_CONTENT,
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    issue.fix_id = f.id
    db.add(issue)
    db.commit()
    return f


@pytest.fixture()
def pending_workflow_file(db: Session, repo: Repository) -> WorkflowFile:
    """A second workflow file (one Fix per workflow file — unique constraint)."""
    wf = WorkflowFile(
        repo_id=repo.id,
        path=".github/workflows/fixes-test-pending.yml",
        content_hash=uuid.uuid4().hex,
        raw_content="on: push\njobs: {}",
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


@pytest.fixture()
def pending_fix(db: Session, pending_workflow_file: WorkflowFile) -> Fix:
    f = Fix(
        workflow_file_id=pending_workflow_file.id,
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o-mini",
        status=FixStatus.pending,
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    return f


def _make_wf_with_issue(
    db: Session, repo: Repository, rule: Rule, n: int
) -> tuple[WorkflowFile, Issue]:
    """A workflow file with a completed analysis and one unresolved issue."""
    wf = WorkflowFile(
        repo_id=repo.id,
        path=f".github/workflows/quota-{n}-{uuid.uuid4().hex[:6]}.yml",
        content_hash=uuid.uuid4().hex,
        raw_content="on: push\njobs: {}",
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    a = Analysis(
        repo_id=repo.id,
        workflow_file_id=wf.id,
        content_hash=wf.content_hash,
        status=AnalysisStatus.completed,
        triggered_by=AnalysisTrigger.manual,
        branch="main",
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    i = Issue(
        analysis_id=a.id,
        workflow_file_id=wf.id,
        rule_id=rule.id,
        fingerprint=uuid.uuid4().hex[:16],
        severity=IssueSeverity.medium,
        category=IssueCategory.reliability,
        message=f"quota issue {n}",
    )
    db.add(i)
    db.commit()
    db.refresh(i)
    return wf, i


# ─── GET /fixes/ ──────────────────────────────────────────────────────────────


def test_list_fixes_empty(
    client: TestClient,
    superuser_token_headers: dict[str, str],
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
    assert response.json() == []


def test_list_fixes_with_data(
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
    assert isinstance(data, list)
    ids = [f["id"] for f in data]
    assert str(ready_fix.id) in ids


def test_list_fixes_filter_by_status(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    ready_fix: Fix,
    repo: Repository,
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/fixes/",
        params={"repo_id": str(repo.id), "status": "ready"},
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert all(f["status"] == "ready" for f in data)
    assert any(f["id"] == str(ready_fix.id) for f in data)


def test_list_fixes_includes_issue_summaries(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    ready_fix: Fix,
    issue: Issue,
    rule: Rule,
    repo: Repository,
    workflow_file: WorkflowFile,
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/fixes/",
        params={"repo_id": str(repo.id)},
        headers=superuser_token_headers,
    )

    # Assert — the fix carries its addressed issues and workflow path
    assert response.status_code == 200
    fix_data = next(f for f in response.json() if f["id"] == str(ready_fix.id))
    assert fix_data["workflow_file_id"] == str(workflow_file.id)
    assert fix_data["workflow_file_path"] == workflow_file.path
    assert fix_data["repo_id"] == str(repo.id)
    issue_ids = [i["id"] for i in fix_data["issues"]]
    assert str(issue.id) in issue_ids
    issue_data = next(i for i in fix_data["issues"] if i["id"] == str(issue.id))
    assert issue_data["rule_slug"] == rule.slug
    assert issue_data["message"] == issue.message


# ─── GET /fixes/{id} ──────────────────────────────────────────────────────────


def test_get_fix_found(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    ready_fix: Fix,
    workflow_file: WorkflowFile,
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
    assert body["full_content"] == _FULL_CONTENT
    # Detail view includes the current file content for diff rendering
    assert body["base_content"] == workflow_file.raw_content


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

    # Assert — queued counts workflow files, not issues
    assert response.status_code == 202
    body = response.json()
    assert body["queued"] == 1
    mock_delay.assert_called()


def test_generate_fixes_for_repo_one_task_per_workflow_file(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    rule: Rule,
) -> None:
    # Arrange — two workflow files, two issues each
    _wf1, issue1 = _make_wf_with_issue(db, repo, rule, 1)
    _wf2, issue2 = _make_wf_with_issue(db, repo, rule, 2)

    # Act
    with patch("app.api.routes.fixes.run_fix_generation.delay") as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/fixes/generate-for-repo/{repo.id}",
            headers=superuser_token_headers,
            json={"issue_ids": [str(issue1.id), str(issue2.id)]},
        )

    # Assert — one generation task per workflow file
    assert response.status_code == 202
    assert response.json()["queued"] == 2
    assert mock_delay.call_count == 2
    queued_groups = [
        set(call.kwargs["issue_ids"]) for call in mock_delay.call_args_list
    ]
    assert {str(issue1.id)} in queued_groups
    assert {str(issue2.id)} in queued_groups


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
    assert body["queued"] == 1
    mock_delay.assert_called_once()
    assert mock_delay.call_args.kwargs["issue_ids"] == [str(issue.id)]
    assert mock_delay.call_args.kwargs["batch_id"]


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


def test_generate_fixes_for_repo_regeneration_allowed_at_quota(
    client: TestClient,
    db: Session,
    org: Organization,
    repo: Repository,
    rule: Rule,
) -> None:
    """A free-tier user at the fixes quota can still REgenerate existing fixes.

    Regeneration deletes the old fixes and recreates the same number, so the
    resulting total is unchanged and must not be blocked (regression test for
    'Fix selected' → 'Failed to queue fixes' once the quota was reached).
    """
    # Arrange — fresh free-tier member so usage isn't polluted by other tests
    user = create_random_user(db)
    db.add(OrgMember(org_id=org.id, user_id=user.id))
    db.commit()
    headers = authentication_token_from_email(client=client, email=user.email, db=db)

    free_fix_limit = 5
    for n in range(free_fix_limit):
        wf, _issue = _make_wf_with_issue(db, repo, rule, n)
        db.add(
            Fix(
                workflow_file_id=wf.id,
                llm_provider=LLMProvider.openai,
                llm_model="gpt-4o-mini",
                status=FixStatus.ready,
            )
        )
    db.commit()

    # Act — regenerate all fixes while already at the quota
    with patch("app.api.routes.fixes.run_fix_generation.delay") as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/fixes/generate-for-repo/{repo.id}",
            headers=headers,
        )

    # Assert
    assert response.status_code == 202, response.json()
    assert response.json()["queued"] == free_fix_limit
    mock_delay.assert_called()


def test_generate_fixes_for_repo_blocks_net_new_over_quota(
    client: TestClient,
    db: Session,
    org: Organization,
    repo: Repository,
    rule: Rule,
) -> None:
    """A free-tier user cannot generate more NET-NEW fixes than the quota."""
    user = create_random_user(db)
    db.add(OrgMember(org_id=org.id, user_id=user.id))
    db.commit()
    headers = authentication_token_from_email(client=client, email=user.email, db=db)

    free_fix_limit = 5
    for n in range(free_fix_limit + 1):
        _make_wf_with_issue(db, repo, rule, n)

    # Act — no existing fixes; requesting limit+1 new ones must be rejected
    with patch("app.api.routes.fixes.run_fix_generation.delay") as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/fixes/generate-for-repo/{repo.id}",
            headers=headers,
        )

    # Assert
    assert response.status_code == 402
    assert "quota" in response.json()["detail"].lower()
    mock_delay.assert_not_called()


def test_generate_fixes_for_repo_replaces_existing_fixes(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    ready_fix: Fix,
    repo: Repository,
    db: Session,
) -> None:
    # Arrange — the workflow file already has a ready fix
    fix_id = ready_fix.id
    with patch("app.api.routes.fixes.run_fix_generation.delay") as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/fixes/generate-for-repo/{repo.id}",
            headers=superuser_token_headers,
        )

    # Assert — existing non-delivered fix deleted, new task queued
    assert response.status_code == 202
    assert response.json()["queued"] == 1
    mock_delay.assert_called()
    db.expire_all()  # clear identity map so get() hits the DB
    assert db.get(Fix, fix_id) is None


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
    workflow_file: WorkflowFile,
) -> None:
    # Act
    with patch(
        "app.workers.tasks.fix_delivery.deliver_fixes_batch.delay"
    ) as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/fixes/deliver-for-workflow",
            headers=superuser_token_headers,
            json={"fix_id": str(ready_fix.id)},
        )

    # Assert
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    mock_delay.assert_called_once()
    call_kwargs = mock_delay.call_args.kwargs
    assert call_kwargs["fix_ids"] == [str(ready_fix.id)]
    assert call_kwargs["pr_branch"] == (
        f"greensecops/fixes-wf-{str(workflow_file.id)[:8]}"
    )


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
            json={"fix_id": str(pending_fix.id)},
        )

    # Assert
    assert response.status_code == 404
    assert "No ready fix" in response.json()["detail"]


def test_deliver_for_workflow_unknown_id_returns_404(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    # Act
    with patch("app.workers.tasks.fix_delivery.deliver_fixes_batch.delay"):
        response = client.post(
            f"{settings.API_V1_STR}/fixes/deliver-for-workflow",
            headers=superuser_token_headers,
            json={"fix_id": str(uuid.uuid4())},
        )

    # Assert
    assert response.status_code == 404


def test_deliver_for_workflow_reuses_existing_pr_branch(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    ready_fix: Fix,
    repo: Repository,
) -> None:
    # Arrange — the fix was delivered before via a PR on a custom branch
    existing_branch = "greensecops/fixes-wf-previous"
    pr = PullRequest(
        repo_id=repo.id,
        pr_branch=existing_branch,
        pr_url=f"https://github.com/{repo.full_name}/pull/98",
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
            f"{settings.API_V1_STR}/fixes/deliver-for-workflow",
            headers=superuser_token_headers,
            json={"fix_id": str(ready_fix.id)},
        )

    assert response.status_code == 202
    assert mock_delay.call_args.kwargs["pr_branch"] == existing_branch


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
    # Act — repo only has a pending fix (not ready)
    with patch("app.workers.tasks.fix_delivery.deliver_fixes_batch.delay"):
        response = client.post(
            f"{settings.API_V1_STR}/fixes/deliver-for-repo/{repo.id}",
            headers=superuser_token_headers,
        )

    # Assert
    assert response.status_code == 404
    assert "No ready fixes" in response.json()["detail"]


# ─── Force re-run tests ───────────────────────────────────────────────────────


def test_generate_fixes_for_repo_preserves_delivered_and_skips_in_task(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    issue: Issue,
    workflow_file: WorkflowFile,
    repo: Repository,
) -> None:
    # Arrange — delivered fix must not be replaced (unique constraint)
    delivered_fix = Fix(
        workflow_file_id=workflow_file.id,
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o-mini",
        status=FixStatus.delivered,
        full_content=_FULL_CONTENT,
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
    workflow_file: WorkflowFile,
    repo: Repository,
) -> None:
    # Arrange — create a delivered fix that should normally be preserved
    delivered_fix = Fix(
        workflow_file_id=workflow_file.id,
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o-mini",
        status=FixStatus.delivered,
        full_content=_FULL_CONTENT,
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


def test_deliver_for_workflow_force_includes_non_ready(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    pending_fix: Fix,
) -> None:
    # Act — pending fix would normally be excluded (no ready fix → 404)
    with patch(
        "app.workers.tasks.fix_delivery.deliver_fixes_batch.delay"
    ) as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/fixes/deliver-for-workflow",
            params={"force": "true"},
            headers=superuser_token_headers,
            json={"fix_id": str(pending_fix.id)},
        )

    # Assert — force=True includes the pending fix
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    mock_delay.assert_called_once()
    call_kwargs = mock_delay.call_args.kwargs
    assert call_kwargs["fix_ids"] == [str(pending_fix.id)]
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
    workflow_file: WorkflowFile,
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
        workflow_file_id=workflow_file.id,
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
    workflow_file: WorkflowFile,
) -> None:
    pr_url = f"https://github.com/{repo.full_name}/pull/101"
    _fix, pr = _make_open_pr_fix(db, repo, workflow_file, pr_url)

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
    workflow_file: WorkflowFile,
) -> None:
    pr_url = f"https://github.com/{repo.full_name}/pull/102"
    _fix, pr = _make_open_pr_fix(db, repo, workflow_file, pr_url)

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
    workflow_file: WorkflowFile,
) -> None:
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
        workflow_file_id=workflow_file.id,
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
    workflow_file: WorkflowFile,
) -> None:
    pr_url = f"https://github.com/{repo.full_name}/pull/104"
    _fix, pr = _make_open_pr_fix(db, repo, workflow_file, pr_url)

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


# ─── run_fix_generation task unit tests ──────────────────────────────────────


def test_run_fix_generation_skipped_publishes_fix_skipped_event(
    db: Session,
    issue: Issue,
    workflow_file: WorkflowFile,
) -> None:
    from app.workers.tasks.fix_generation import run_fix_generation

    # Arrange — the workflow file has a delivered fix but no pending one; the
    # task should skip and fire fix.skipped
    delivered_fix = Fix(
        workflow_file_id=workflow_file.id,
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o-mini",
        status=FixStatus.delivered,
        full_content=_FULL_CONTENT,
    )
    db.add(delivered_fix)
    db.commit()

    with patch("app.workers.tasks.fix_generation.events_pub.publish_event") as mock_pub:
        result = run_fix_generation(issue_ids=[str(issue.id)])

    assert result == {"status": "skipped", "detail": "no_pending_fix"}
    published_events = [call.args[0].event for call in mock_pub.call_args_list]
    assert "fix.skipped" in published_events


# ─── regenerate helpers ──────────────────────────────────────────────────────


def _make_pr(
    db: Session, repo: Repository, pr_state: str, pr_branch: str
) -> PullRequest:
    pr = PullRequest(
        repo_id=repo.id,
        pr_branch=pr_branch,
        pr_url=f"https://github.com/{repo.full_name}/pull/{uuid.uuid4().int % 10**4}",
        pr_state=pr_state,
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)
    return pr


def _make_fix(
    db: Session,
    workflow_file_id: uuid.UUID,
    status: FixStatus = FixStatus.ready,
    pr_id: uuid.UUID | None = None,
) -> Fix:
    f = Fix(
        workflow_file_id=workflow_file_id,
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o-mini",
        status=status,
        pr_id=pr_id,
        full_content=_FULL_CONTENT,
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    return f


# ─── POST /fixes/regenerate-for-repo/{repo_id} ───────────────────────────────


def test_regenerate_for_repo_replaces_fixes_and_queues_per_workflow(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    rule: Rule,
) -> None:
    # Arrange — two workflow files with unresolved issues and regenerable fixes
    wf1, issue1 = _make_wf_with_issue(db, repo, rule, 1)
    wf2, issue2 = _make_wf_with_issue(db, repo, rule, 2)
    old_ids = {_make_fix(db, wf1.id, FixStatus.ready).id}
    old_ids.add(_make_fix(db, wf2.id, FixStatus.failed).id)

    # Act
    with patch("app.api.routes.fixes.run_fix_generation.delay") as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/fixes/regenerate-for-repo/{repo.id}",
            headers=superuser_token_headers,
        )

    # Assert — one task per workflow file, sharing one batch
    assert response.status_code == 202
    assert response.json()["queued"] == 2
    assert mock_delay.call_count == 2
    queued_issue_ids = sorted(
        i for call in mock_delay.call_args_list for i in call.kwargs["issue_ids"]
    )
    assert queued_issue_ids == sorted([str(issue1.id), str(issue2.id)])
    assert len({call.kwargs["batch_id"] for call in mock_delay.call_args_list}) == 1

    # Old fixes replaced by fresh pending ones
    db.expire_all()
    from sqlmodel import select as sql_select

    for wf in (wf1, wf2):
        new_fix = db.exec(sql_select(Fix).where(Fix.workflow_file_id == wf.id)).one()
        assert new_fix.id not in old_ids
        assert new_fix.status == FixStatus.pending


def test_regenerate_for_repo_skips_merged_pr_fix(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    rule: Rule,
    workflow_file: WorkflowFile,
    issue: Issue,
) -> None:
    # Arrange — a merged-PR fix (with an unresolved issue) plus a regenerable fix
    pr = _make_pr(db, repo, "merged", "greensecops/regen-repo-merged")
    merged_fix_id = _make_fix(db, workflow_file.id, FixStatus.delivered, pr_id=pr.id).id
    wf, _wf_issue = _make_wf_with_issue(db, repo, rule, 3)
    other_fix_id = _make_fix(db, wf.id, FixStatus.ready).id
    pr_id = pr.id

    # Act
    with patch("app.api.routes.fixes.run_fix_generation.delay"):
        response = client.post(
            f"{settings.API_V1_STR}/fixes/regenerate-for-repo/{repo.id}",
            headers=superuser_token_headers,
        )

    # Assert — merged code changes were already applied: fix and PR survive
    assert response.status_code == 202
    assert response.json()["queued"] == 1
    db.expire_all()
    assert db.get(Fix, merged_fix_id) is not None
    assert db.get(PullRequest, pr_id) is not None
    assert db.get(Fix, other_fix_id) is None


def test_regenerate_for_repo_skips_in_flight_fix(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    rule: Rule,
    pending_fix: Fix,
) -> None:
    # Arrange — an in-flight (pending) fix plus a regenerable one
    wf, _issue = _make_wf_with_issue(db, repo, rule, 4)
    _make_fix(db, wf.id, FixStatus.ready)
    pending_fix_id = pending_fix.id

    # Act
    with patch("app.api.routes.fixes.run_fix_generation.delay"):
        response = client.post(
            f"{settings.API_V1_STR}/fixes/regenerate-for-repo/{repo.id}",
            headers=superuser_token_headers,
        )

    # Assert — the worker keeps processing the in-flight fix undisturbed
    assert response.status_code == 202
    assert response.json()["queued"] == 1
    db.expire_all()
    assert db.get(Fix, pending_fix_id) is not None


def test_regenerate_for_repo_sweeps_orphaned_closed_pr(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    workflow_file: WorkflowFile,
    issue: Issue,
) -> None:
    # Arrange — a delivered fix on a closed PR; regenerating orphans the record
    pr = _make_pr(db, repo, "closed", "greensecops/regen-repo-closed")
    _make_fix(db, workflow_file.id, FixStatus.delivered, pr_id=pr.id)
    pr_id = pr.id

    # Act
    with patch("app.api.routes.fixes.run_fix_generation.delay"):
        response = client.post(
            f"{settings.API_V1_STR}/fixes/regenerate-for-repo/{repo.id}",
            headers=superuser_token_headers,
        )

    # Assert — the closed record is forgotten so redelivery is not
    # auto-rejected by the closed-PR guard
    assert response.status_code == 202
    assert response.json()["queued"] == 1
    db.expire_all()
    assert db.get(PullRequest, pr_id) is None


def test_regenerate_for_repo_keeps_closed_pr_referenced_by_surviving_fix(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    workflow_file: WorkflowFile,
    pending_workflow_file: WorkflowFile,
    issue: Issue,
) -> None:
    # Arrange — a closed PR shared by a regenerable fix and an in-flight one
    pr = _make_pr(db, repo, "closed", "greensecops/regen-repo-shared")
    _make_fix(db, workflow_file.id, FixStatus.delivered, pr_id=pr.id)
    surviving_fix_id = _make_fix(
        db, pending_workflow_file.id, FixStatus.delivering, pr_id=pr.id
    ).id
    pr_id = pr.id

    # Act
    with patch("app.api.routes.fixes.run_fix_generation.delay"):
        response = client.post(
            f"{settings.API_V1_STR}/fixes/regenerate-for-repo/{repo.id}",
            headers=superuser_token_headers,
        )

    # Assert — deleting the PR would SET NULL the surviving fix's pr_id
    assert response.status_code == 202
    db.expire_all()
    assert db.get(PullRequest, pr_id) is not None
    surviving_fix = db.get(Fix, surviving_fix_id)
    assert surviving_fix is not None
    assert surviving_fix.pr_id == pr_id


def test_regenerate_for_repo_regenerates_guard_rejected_fix(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    workflow_file: WorkflowFile,
    issue: Issue,
) -> None:
    """A fix auto-rejected by the closed-PR delivery guard (rejected, never
    delivered, linked to the closed PR) is regenerated like a delivered one."""
    pr = _make_pr(db, repo, "closed", "greensecops/regen-repo-rejected")
    fix_id = _make_fix(db, workflow_file.id, FixStatus.rejected, pr_id=pr.id).id
    pr_id = pr.id

    with patch("app.api.routes.fixes.run_fix_generation.delay") as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/fixes/regenerate-for-repo/{repo.id}",
            headers=superuser_token_headers,
        )

    assert response.status_code == 202
    assert response.json()["queued"] == 1
    mock_delay.assert_called_once()
    db.expire_all()
    assert db.get(Fix, fix_id) is None
    assert db.get(PullRequest, pr_id) is None


def test_regenerate_for_repo_keeps_fix_without_unresolved_issues(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    ready_fix: Fix,
    issue: Issue,
) -> None:
    # Arrange — the fix's only issue is resolved: nothing to regenerate from
    issue.resolved_at = datetime.now(UTC)
    db.add(issue)
    db.commit()
    fix_id = ready_fix.id

    # Act
    with patch("app.api.routes.fixes.run_fix_generation.delay") as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/fixes/regenerate-for-repo/{repo.id}",
            headers=superuser_token_headers,
        )

    # Assert
    assert response.status_code == 202
    assert response.json()["queued"] == 0
    mock_delay.assert_not_called()
    db.expire_all()
    assert db.get(Fix, fix_id) is not None


def test_regenerate_for_repo_without_fixes_returns_zero(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
) -> None:
    with patch("app.api.routes.fixes.run_fix_generation.delay") as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/fixes/regenerate-for-repo/{repo.id}",
            headers=superuser_token_headers,
        )

    assert response.status_code == 202
    assert response.json()["queued"] == 0
    mock_delay.assert_not_called()


def test_regenerate_for_repo_allowed_at_quota(
    client: TestClient,
    db: Session,
    org: Organization,
    repo: Repository,
    rule: Rule,
) -> None:
    """A free-tier user at the fixes quota can still regenerate all fixes —
    the delete-and-recreate nets to zero."""
    user = create_random_user(db)
    db.add(OrgMember(org_id=org.id, user_id=user.id))
    db.commit()
    headers = authentication_token_from_email(client=client, email=user.email, db=db)

    free_fix_limit = 5
    for n in range(free_fix_limit):
        wf, _issue = _make_wf_with_issue(db, repo, rule, n)
        _make_fix(db, wf.id, FixStatus.ready)

    with patch("app.api.routes.fixes.run_fix_generation.delay") as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/fixes/regenerate-for-repo/{repo.id}",
            headers=headers,
        )

    assert response.status_code == 202, response.json()
    assert response.json()["queued"] == free_fix_limit
    mock_delay.assert_called()


def test_regenerate_for_repo_not_found(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/fixes/regenerate-for-repo/{uuid.uuid4()}",
        headers=superuser_token_headers,
    )
    assert response.status_code == 404


def test_regenerate_for_repo_denied_for_non_member(
    client: TestClient,
    db: Session,
    repo: Repository,
) -> None:
    user = create_random_user(db)
    headers = authentication_token_from_email(client=client, email=user.email, db=db)

    response = client.post(
        f"{settings.API_V1_STR}/fixes/regenerate-for-repo/{repo.id}",
        headers=headers,
    )
    assert response.status_code == 404


def test_regenerate_for_repo_inaccessible_repo(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
) -> None:
    repo.is_accessible = False
    db.add(repo)
    db.commit()

    response = client.post(
        f"{settings.API_V1_STR}/fixes/regenerate-for-repo/{repo.id}",
        headers=superuser_token_headers,
    )
    assert response.status_code == 403


# ─── POST /fixes/regenerate-for-workflow/{fix_id} ────────────────────────────


def test_regenerate_for_workflow_replaces_fix(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    workflow_file: WorkflowFile,
    ready_fix: Fix,
    issue: Issue,
) -> None:
    old_fix_id = ready_fix.id

    with patch("app.api.routes.fixes.run_fix_generation.delay") as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/fixes/regenerate-for-workflow/{old_fix_id}",
            headers=superuser_token_headers,
        )

    assert response.status_code == 202
    assert response.json()["queued"] == 1
    mock_delay.assert_called_once()
    assert mock_delay.call_args.kwargs["issue_ids"] == [str(issue.id)]
    assert mock_delay.call_args.kwargs["batch_id"]

    db.expire_all()
    from sqlmodel import select as sql_select

    assert db.get(Fix, old_fix_id) is None
    new_fix = db.exec(
        sql_select(Fix).where(Fix.workflow_file_id == workflow_file.id)
    ).one()
    assert new_fix.status == FixStatus.pending


def test_regenerate_for_workflow_rejects_in_flight_fix(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    pending_fix: Fix,
) -> None:
    fix_id = pending_fix.id

    response = client.post(
        f"{settings.API_V1_STR}/fixes/regenerate-for-workflow/{fix_id}",
        headers=superuser_token_headers,
    )

    assert response.status_code == 409
    db.expire_all()
    assert db.get(Fix, fix_id) is not None


def test_regenerate_for_workflow_rejects_merged_pr_fix(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    workflow_file: WorkflowFile,
    issue: Issue,
) -> None:
    pr = _make_pr(db, repo, "merged", "greensecops/regen-wf-merged")
    fix_id = _make_fix(db, workflow_file.id, FixStatus.delivered, pr_id=pr.id).id
    pr_id = pr.id

    response = client.post(
        f"{settings.API_V1_STR}/fixes/regenerate-for-workflow/{fix_id}",
        headers=superuser_token_headers,
    )

    assert response.status_code == 409
    db.expire_all()
    assert db.get(Fix, fix_id) is not None
    assert db.get(PullRequest, pr_id) is not None


def test_regenerate_for_workflow_rejects_when_issues_resolved(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    ready_fix: Fix,
    issue: Issue,
) -> None:
    # Arrange — the workflow file's only issue is resolved
    issue.resolved_at = datetime.now(UTC)
    db.add(issue)
    db.commit()
    fix_id = ready_fix.id

    response = client.post(
        f"{settings.API_V1_STR}/fixes/regenerate-for-workflow/{fix_id}",
        headers=superuser_token_headers,
    )

    assert response.status_code == 409
    db.expire_all()
    assert db.get(Fix, fix_id) is not None


def test_regenerate_for_workflow_sweeps_orphaned_closed_pr(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    workflow_file: WorkflowFile,
    issue: Issue,
) -> None:
    pr = _make_pr(db, repo, "closed", "greensecops/regen-wf-closed")
    fix_id = _make_fix(db, workflow_file.id, FixStatus.delivered, pr_id=pr.id).id
    pr_id = pr.id

    with patch("app.api.routes.fixes.run_fix_generation.delay"):
        response = client.post(
            f"{settings.API_V1_STR}/fixes/regenerate-for-workflow/{fix_id}",
            headers=superuser_token_headers,
        )

    assert response.status_code == 202
    db.expire_all()
    assert db.get(PullRequest, pr_id) is None


def test_regenerate_for_workflow_keeps_shared_closed_pr(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    workflow_file: WorkflowFile,
    pending_workflow_file: WorkflowFile,
    issue: Issue,
) -> None:
    # Arrange — a closed repo-wide PR whose fixes span two workflow files;
    # only one of them is regenerated
    pr = _make_pr(db, repo, "closed", "greensecops/regen-wf-shared")
    fix_id = _make_fix(db, workflow_file.id, FixStatus.delivered, pr_id=pr.id).id
    sibling_fix_id = _make_fix(
        db, pending_workflow_file.id, FixStatus.delivered, pr_id=pr.id
    ).id
    pr_id = pr.id

    with patch("app.api.routes.fixes.run_fix_generation.delay"):
        response = client.post(
            f"{settings.API_V1_STR}/fixes/regenerate-for-workflow/{fix_id}",
            headers=superuser_token_headers,
        )

    # Assert — deleting the PR would SET NULL the sibling's pr_id
    assert response.status_code == 202
    db.expire_all()
    assert db.get(PullRequest, pr_id) is not None
    sibling_fix = db.get(Fix, sibling_fix_id)
    assert sibling_fix is not None
    assert sibling_fix.pr_id == pr_id


def test_regenerate_for_workflow_allowed_at_quota(
    client: TestClient,
    db: Session,
    org: Organization,
    repo: Repository,
    rule: Rule,
) -> None:
    """A free-tier user at the fixes quota can still regenerate one fix."""
    user = create_random_user(db)
    db.add(OrgMember(org_id=org.id, user_id=user.id))
    db.commit()
    headers = authentication_token_from_email(client=client, email=user.email, db=db)

    free_fix_limit = 5
    target_fix_id = None
    for n in range(free_fix_limit):
        wf, _issue = _make_wf_with_issue(db, repo, rule, n)
        target_fix_id = _make_fix(db, wf.id, FixStatus.ready).id

    with patch("app.api.routes.fixes.run_fix_generation.delay") as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/fixes/regenerate-for-workflow/{target_fix_id}",
            headers=headers,
        )

    assert response.status_code == 202, response.json()
    assert response.json()["queued"] == 1
    mock_delay.assert_called_once()


def test_regenerate_for_workflow_not_found(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/fixes/regenerate-for-workflow/{uuid.uuid4()}",
        headers=superuser_token_headers,
    )
    assert response.status_code == 404


def test_regenerate_for_workflow_denied_for_non_member(
    client: TestClient,
    db: Session,
    ready_fix: Fix,
) -> None:
    user = create_random_user(db)
    headers = authentication_token_from_email(client=client, email=user.email, db=db)

    response = client.post(
        f"{settings.API_V1_STR}/fixes/regenerate-for-workflow/{ready_fix.id}",
        headers=headers,
    )
    assert response.status_code == 404


def test_regenerate_for_workflow_inaccessible_repo(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    ready_fix: Fix,
) -> None:
    repo.is_accessible = False
    db.add(repo)
    db.commit()

    response = client.post(
        f"{settings.API_V1_STR}/fixes/regenerate-for-workflow/{ready_fix.id}",
        headers=superuser_token_headers,
    )
    assert response.status_code == 403
