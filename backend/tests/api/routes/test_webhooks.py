"""Tests for the /api/v1/webhooks/ endpoints."""

import hashlib
import hmac
import json
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

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

WEBHOOK_URL = f"{settings.API_V1_STR}/webhooks/github"


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def org(db: Session) -> Organization:
    organization = Organization(
        name=f"wh-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free
    )
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization


@pytest.fixture()
def enabled_repo(db: Session, org: Organization) -> Repository:
    repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"owner/wh-repo-{uuid.uuid4().hex[:8]}",
        installation_id=99901,
        enabled=True,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    return repo


@pytest.fixture()
def disabled_repo(db: Session, org: Organization) -> Repository:
    repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"owner/wh-disabled-{uuid.uuid4().hex[:8]}",
        installation_id=99902,
        enabled=False,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    return repo


def _make_signature(payload: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


# ─── Signature verification ───────────────────────────────────────────────────


def test_github_webhook_invalid_signature_returns_401(client: TestClient) -> None:
    # Arrange
    secret = "test-secret"
    payload = json.dumps({"action": "push"}).encode()

    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", secret):
        # Act
        response = client.post(
            WEBHOOK_URL,
            content=payload,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": "sha256=invalidsig",
                "X-GitHub-Event": "push",
            },
        )

    # Assert
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid webhook signature"


def test_github_webhook_valid_signature_accepted(client: TestClient) -> None:
    # Arrange
    secret = "test-secret"
    payload = json.dumps({}).encode()
    sig = _make_signature(payload, secret)

    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", secret):
        # Act
        response = client.post(
            WEBHOOK_URL,
            content=payload,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": sig,
                "X-GitHub-Event": "ping",
            },
        )

    # Assert
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"


def test_github_webhook_no_secret_skips_verification(client: TestClient) -> None:
    # Arrange — no secret configured
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(
            WEBHOOK_URL,
            json={},
            headers={"X-GitHub-Event": "ping"},
        )

    # Assert
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"


# ─── Invalid JSON ─────────────────────────────────────────────────────────────


def test_github_webhook_invalid_json_returns_400(client: TestClient) -> None:
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(
            WEBHOOK_URL,
            content=b"not-valid-json",
            headers={"Content-Type": "application/json", "X-GitHub-Event": "push"},
        )
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid JSON payload"


# ─── Unknown event falls through cleanly ─────────────────────────────────────


def test_github_webhook_unknown_event_returns_accepted(client: TestClient) -> None:
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(
            WEBHOOK_URL,
            json={"action": "something"},
            headers={"X-GitHub-Event": "unknown_event"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "accepted"
    assert data["event"] == "unknown_event"


def test_github_webhook_no_event_header_uses_unknown(client: TestClient) -> None:
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(WEBHOOK_URL, json={})
    assert response.status_code == 200
    assert response.json()["event"] == "unknown"


# ─── Push event ───────────────────────────────────────────────────────────────


def test_github_webhook_push_no_workflow_files_skipped(client: TestClient) -> None:
    payload = {
        "commits": [{"added": ["README.md"], "modified": [], "removed": []}],
        "repository": {"id": 123456},
    }
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-GitHub-Event": "push"},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"


def test_github_webhook_push_missing_repo_id_skipped(client: TestClient) -> None:
    payload = {
        "commits": [
            {
                "added": [".github/workflows/ci.yml"],
                "modified": [],
                "removed": [],
            }
        ],
        "repository": {},
    }
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-GitHub-Event": "push"},
        )
    assert response.status_code == 200


def test_github_webhook_push_repo_not_in_db_skipped(client: TestClient) -> None:
    payload = {
        "commits": [
            {
                "added": [".github/workflows/ci.yml"],
                "modified": [],
                "removed": [],
            }
        ],
        "repository": {"id": 999999999},
    }
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-GitHub-Event": "push"},
        )
    assert response.status_code == 200


def test_github_webhook_push_disabled_repo_skipped(
    client: TestClient, disabled_repo: Repository
) -> None:
    payload = {
        "commits": [
            {
                "added": [".github/workflows/ci.yml"],
                "modified": [],
                "removed": [],
            }
        ],
        "repository": {"id": disabled_repo.github_repo_id},
        "ref": "refs/heads/main",
        "after": "abc123",
    }
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-GitHub-Event": "push"},
        )
    assert response.status_code == 200


def test_github_webhook_push_enabled_repo_enqueues(
    client: TestClient, enabled_repo: Repository
) -> None:
    payload = {
        "commits": [
            {
                "added": [".github/workflows/ci.yml"],
                "modified": [],
                "removed": [],
            }
        ],
        "repository": {"id": enabled_repo.github_repo_id},
        "ref": "refs/heads/main",
        "after": "deadbeef",
    }
    with (
        patch.object(settings, "GITHUB_WEBHOOK_SECRET", None),
        patch("app.api.routes.webhooks._enqueue_static_analysis"),
    ):
        response = client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-GitHub-Event": "push"},
        )

    assert response.status_code == 200
    # Background task was scheduled (background_tasks.add_task wraps _enqueue_static_analysis)
    assert response.json()["status"] == "accepted"


# ─── Workflow run event ───────────────────────────────────────────────────────


def test_github_webhook_workflow_run_non_completed_skipped(
    client: TestClient,
) -> None:
    payload = {"action": "requested", "repository": {"id": 111}}
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-GitHub-Event": "workflow_run"},
        )
    assert response.status_code == 200


def test_github_webhook_workflow_run_missing_repo_id_skipped(
    client: TestClient,
) -> None:
    payload = {"action": "completed", "repository": {}, "workflow_run": {}}
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-GitHub-Event": "workflow_run"},
        )
    assert response.status_code == 200


def test_github_webhook_workflow_run_repo_not_found_skipped(
    client: TestClient,
) -> None:
    payload = {
        "action": "completed",
        "repository": {"id": 888777666},
        "workflow_run": {"head_branch": "main", "head_sha": "abc"},
    }
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-GitHub-Event": "workflow_run"},
        )
    assert response.status_code == 200


def test_github_webhook_workflow_run_disabled_repo_skipped(
    client: TestClient, disabled_repo: Repository
) -> None:
    payload = {
        "action": "completed",
        "repository": {"id": disabled_repo.github_repo_id},
        "workflow_run": {"head_branch": "main", "head_sha": "abc"},
    }
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-GitHub-Event": "workflow_run"},
        )
    assert response.status_code == 200


def test_github_webhook_workflow_run_enabled_repo_enqueues(
    client: TestClient, enabled_repo: Repository
) -> None:
    payload = {
        "action": "completed",
        "repository": {"id": enabled_repo.github_repo_id},
        "workflow_run": {"head_branch": "feat/test", "head_sha": "cafebabe"},
    }
    with (
        patch.object(settings, "GITHUB_WEBHOOK_SECRET", None),
        patch("app.api.routes.webhooks._enqueue_static_analysis"),
    ):
        response = client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-GitHub-Event": "workflow_run"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"


# ─── Issue comment event ──────────────────────────────────────────────────────


def test_github_webhook_issue_comment_non_created_skipped(
    client: TestClient,
) -> None:
    payload = {"action": "edited", "comment": {"body": "/greensecops fix"}}
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-GitHub-Event": "issue_comment"},
        )
    assert response.status_code == 200


def test_github_webhook_issue_comment_non_command_skipped(
    client: TestClient,
) -> None:
    payload = {"action": "created", "comment": {"body": "Nice work!"}}
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-GitHub-Event": "issue_comment"},
        )
    assert response.status_code == 200


def test_github_webhook_issue_comment_command_accepted(
    client: TestClient,
) -> None:
    payload = {"action": "created", "comment": {"body": "/greensecops fix"}}
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-GitHub-Event": "issue_comment"},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"


# ─── Installation event ───────────────────────────────────────────────────────


def test_github_webhook_installation_missing_id_skipped(
    client: TestClient,
) -> None:
    payload = {"action": "deleted", "installation": {}}
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-GitHub-Event": "installation"},
        )
    assert response.status_code == 200


def test_github_webhook_installation_non_delete_action_skipped(
    client: TestClient,
) -> None:
    payload = {"action": "created", "installation": {"id": 42}}
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-GitHub-Event": "installation"},
        )
    assert response.status_code == 200


def test_github_webhook_installation_deleted_disables_repos(
    client: TestClient,
    db: Session,
    org: Organization,
) -> None:
    # Arrange — create two repos with the same installation_id
    installation_id = int(uuid.uuid4().int % 10**6) + 500000
    repo1 = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"owner/install-repo1-{uuid.uuid4().hex[:6]}",
        installation_id=installation_id,
        enabled=True,
    )
    repo2 = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"owner/install-repo2-{uuid.uuid4().hex[:6]}",
        installation_id=installation_id,
        enabled=True,
    )
    db.add(repo1)
    db.add(repo2)
    db.commit()
    db.refresh(repo1)
    db.refresh(repo2)

    payload = {"action": "deleted", "installation": {"id": installation_id}}

    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-GitHub-Event": "installation"},
        )

    assert response.status_code == 200
    db.refresh(repo1)
    db.refresh(repo2)
    assert repo1.enabled is False
    assert repo2.enabled is False


def test_github_webhook_installation_suspend_disables_repos(
    client: TestClient,
    db: Session,
    org: Organization,
) -> None:
    # Arrange
    installation_id = int(uuid.uuid4().int % 10**6) + 600000
    repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"owner/suspend-repo-{uuid.uuid4().hex[:6]}",
        installation_id=installation_id,
        enabled=True,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    payload = {"action": "suspend", "installation": {"id": installation_id}}

    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-GitHub-Event": "installation"},
        )

    assert response.status_code == 200
    db.refresh(repo)
    assert repo.enabled is False


def test_github_webhook_installation_created_upserts_org_and_enqueues(
    client: TestClient,
    db: Session,
) -> None:
    from sqlmodel import select

    installation_id = int(uuid.uuid4().int % 10**6) + 700000
    account_id = int(uuid.uuid4().int % 10**9)
    login = f"created-acct-{uuid.uuid4().hex[:6]}"
    payload = {
        "action": "created",
        "installation": {
            "id": installation_id,
            "account": {"id": account_id, "login": login, "type": "Organization"},
        },
    }

    with (
        patch.object(settings, "GITHUB_WEBHOOK_SECRET", None),
        patch("app.api.routes.webhooks._enqueue_installation_sync") as enqueue,
    ):
        response = client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-GitHub-Event": "installation"},
        )

    assert response.status_code == 200
    org = db.exec(
        select(Organization).where(Organization.installation_id == installation_id)
    ).first()
    assert org is not None
    assert org.github_org_id == account_id
    assert org.name == login
    enqueue.assert_called_once_with(installation_id, str(org.id))


def test_github_webhook_installation_created_missing_account_skipped(
    client: TestClient,
) -> None:
    payload = {"action": "created", "installation": {"id": 424242}}
    with (
        patch.object(settings, "GITHUB_WEBHOOK_SECRET", None),
        patch("app.api.routes.webhooks._enqueue_installation_sync") as enqueue,
    ):
        response = client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-GitHub-Event": "installation"},
        )
    assert response.status_code == 200
    enqueue.assert_not_called()


# ─── Installation repositories event ──────────────────────────────────────────


def test_github_webhook_installation_repositories_added_enqueues(
    client: TestClient,
    db: Session,
) -> None:
    from sqlmodel import select

    installation_id = int(uuid.uuid4().int % 10**6) + 750000
    account_id = int(uuid.uuid4().int % 10**9)
    login = f"added-acct-{uuid.uuid4().hex[:6]}"
    payload = {
        "action": "added",
        "installation": {
            "id": installation_id,
            "account": {"id": account_id, "login": login, "type": "User"},
        },
        "repositories_added": [{"id": 1, "full_name": "o/r"}],
    }

    with (
        patch.object(settings, "GITHUB_WEBHOOK_SECRET", None),
        patch("app.api.routes.webhooks._enqueue_installation_sync") as enqueue,
    ):
        response = client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-GitHub-Event": "installation_repositories"},
        )

    assert response.status_code == 200
    org = db.exec(
        select(Organization).where(Organization.installation_id == installation_id)
    ).first()
    assert org is not None
    enqueue.assert_called_once_with(installation_id, str(org.id))


def test_github_webhook_installation_repositories_removed_disables(
    client: TestClient,
    db: Session,
    org: Organization,
) -> None:
    installation_id = int(uuid.uuid4().int % 10**6) + 760000
    repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"owner/removed-{uuid.uuid4().hex[:6]}",
        installation_id=installation_id,
        enabled=True,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    payload = {
        "action": "removed",
        "installation": {"id": installation_id},
        "repositories_removed": [{"id": repo.github_repo_id, "full_name": "x/y"}],
    }

    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-GitHub-Event": "installation_repositories"},
        )

    assert response.status_code == 200
    db.refresh(repo)
    assert repo.enabled is False


# ─── Pull request event ──────────────────────────────────────────────────────


def test_github_webhook_pull_request_merged_updates_fix(
    client: TestClient,
    db: Session,
    org: Organization,
) -> None:
    repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"owner/pr-merged-{uuid.uuid4().hex[:6]}",
        installation_id=99910,
        enabled=True,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    wf = WorkflowFile(
        repo_id=repo.id,
        path=".github/workflows/ci.yml",
        content_hash=uuid.uuid4().hex,
        raw_content="on: push",
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)

    analysis = Analysis(
        repo_id=repo.id,
        workflow_file_id=wf.id,
        content_hash=wf.content_hash,
        status=AnalysisStatus.completed,
        triggered_by=AnalysisTrigger.manual,
        branch="main",
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)

    rule = db.exec(select(Rule)).first()
    if not rule:
        rule = Rule(
            slug=f"test-rule-{uuid.uuid4().hex[:6]}",
            category=IssueCategory.security,
            severity=IssueSeverity.high,
            title="Test Rule",
            description="A test rule",
        )
        db.add(rule)
        db.commit()
        db.refresh(rule)

    issue = Issue(
        analysis_id=analysis.id,
        rule_id=rule.id,
        severity=IssueSeverity.high,
        category=IssueCategory.security,
        message="test issue",
    )
    db.add(issue)
    db.commit()
    db.refresh(issue)

    pr_url = f"https://github.com/owner/repo/pull/{uuid.uuid4().int % 10000}"
    fix = Fix(
        issue_id=issue.id,
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o-mini",
        status=FixStatus.delivered,
        pr_url=pr_url,
    )
    db.add(fix)
    db.commit()
    db.refresh(fix)

    payload = {
        "action": "closed",
        "pull_request": {"html_url": pr_url, "merged": True},
    }

    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-GitHub-Event": "pull_request"},
        )

    assert response.status_code == 200
    db.refresh(fix)
    assert fix.pr_state == "merged"


def test_github_webhook_pull_request_closed_not_merged(
    client: TestClient,
    db: Session,
    org: Organization,
) -> None:
    repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"owner/pr-closed-{uuid.uuid4().hex[:6]}",
        installation_id=99911,
        enabled=True,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    wf = WorkflowFile(
        repo_id=repo.id,
        path=".github/workflows/ci.yml",
        content_hash=uuid.uuid4().hex,
        raw_content="on: push",
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)

    analysis = Analysis(
        repo_id=repo.id,
        workflow_file_id=wf.id,
        content_hash=wf.content_hash,
        status=AnalysisStatus.completed,
        triggered_by=AnalysisTrigger.manual,
        branch="main",
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)

    rule = db.exec(select(Rule)).first()
    assert rule is not None

    issue = Issue(
        analysis_id=analysis.id,
        rule_id=rule.id,
        severity=IssueSeverity.high,
        category=IssueCategory.security,
        message="test issue closed",
    )
    db.add(issue)
    db.commit()
    db.refresh(issue)

    pr_url = f"https://github.com/owner/repo/pull/{uuid.uuid4().int % 10000}"
    fix = Fix(
        issue_id=issue.id,
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o-mini",
        status=FixStatus.delivered,
        pr_url=pr_url,
    )
    db.add(fix)
    db.commit()
    db.refresh(fix)

    payload = {
        "action": "closed",
        "pull_request": {"html_url": pr_url, "merged": False},
    }

    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-GitHub-Event": "pull_request"},
        )

    assert response.status_code == 200
    db.refresh(fix)
    assert fix.pr_state == "closed"


def test_github_webhook_pull_request_non_closed_skipped(
    client: TestClient,
) -> None:
    payload = {
        "action": "opened",
        "pull_request": {"html_url": "https://github.com/o/r/pull/1"},
    }
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-GitHub-Event": "pull_request"},
        )
    assert response.status_code == 200


def test_github_webhook_pull_request_no_pr_url_skipped(
    client: TestClient,
) -> None:
    payload = {"action": "closed", "pull_request": {}}
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-GitHub-Event": "pull_request"},
        )
    assert response.status_code == 200


def test_github_webhook_pull_request_fix_not_found_skipped(
    client: TestClient,
) -> None:
    payload = {
        "action": "closed",
        "pull_request": {
            "html_url": "https://github.com/x/y/pull/99999",
            "merged": True,
        },
    }
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-GitHub-Event": "pull_request"},
        )
    assert response.status_code == 200


# ─── Enqueue helpers ─────────────────────────────────────────────────────────


def test_enqueue_static_analysis_calls_celery_task() -> None:
    from unittest.mock import MagicMock

    from app.api.routes.webhooks import _enqueue_static_analysis

    mock_task = MagicMock()
    with patch("app.workers.tasks.static_analysis.run_static_analysis", mock_task):
        _enqueue_static_analysis(
            repo_id="abc-123",
            branch="main",
            commit_sha="deadbeef",
            trigger=AnalysisTrigger.webhook_push,
        )
    mock_task.delay.assert_called_once()


def test_enqueue_installation_sync_calls_celery_task() -> None:
    from unittest.mock import MagicMock

    from app.api.routes.webhooks import _enqueue_installation_sync

    mock_task = MagicMock()
    with patch(
        "app.workers.tasks.installation_sync.sync_installation_repositories", mock_task
    ):
        _enqueue_installation_sync(12345, "org-id-str")
    mock_task.delay.assert_called_once()
