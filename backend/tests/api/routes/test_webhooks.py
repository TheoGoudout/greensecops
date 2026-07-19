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
    CIStatus,
    Fix,
    FixStatus,
    Issue,
    IssueCategory,
    IssueResolutionReason,
    IssueSeverity,
    IssueStatus,
    LLMProvider,
    Organization,
    PullRequest,
    PullRequestState,
    Repository,
    RepositoryStatus,
    ReviewDecision,
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


def test_github_webhook_no_secret_fails_closed_in_production(
    client: TestClient,
) -> None:
    # Outside local dev, an unconfigured webhook secret must reject the request
    # rather than processing an unverified payload.
    with (
        patch.object(settings, "GITHUB_WEBHOOK_SECRET", None),
        patch.object(settings, "ENVIRONMENT", "production"),
    ):
        response = client.post(
            WEBHOOK_URL,
            content=json.dumps({"action": "push"}).encode(),
            headers={"Content-Type": "application/json", "X-GitHub-Event": "push"},
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "Webhook secret not configured"


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

    pr_url = f"https://github.com/owner/repo/pull/{uuid.uuid4().int % 10**9}"
    pr = PullRequest(
        repo_id=repo.id,
        pr_branch="greensecops/fix-test-merged",
        pr_url=pr_url,
        pr_state="open",
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)
    fix = Fix(
        workflow_file_id=wf.id,
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o-mini",
        status=FixStatus.delivered,
        pr_id=pr.id,
    )
    db.add(fix)
    db.commit()
    db.refresh(fix)
    # Link the issue to the fix so merge resolves it.
    issue.fix_id = fix.id
    db.add(issue)
    db.commit()

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
    db.refresh(pr)
    assert pr.pr_state == "merged"
    # A3: the merged PR's delivered fix lands, and its issue resolves as merged.
    db.refresh(fix)
    assert fix.status == FixStatus.landed
    db.refresh(issue)
    assert issue.resolved_at is not None
    assert issue.resolution_reason == IssueResolutionReason.merged
    assert issue.status == IssueStatus.resolved


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

    pr_url = f"https://github.com/owner/repo/pull/{uuid.uuid4().int % 10**9}"
    pr = PullRequest(
        repo_id=repo.id,
        pr_branch="greensecops/fix-test-closed",
        pr_url=pr_url,
        pr_state="open",
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)
    fix = Fix(
        workflow_file_id=wf.id,
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o-mini",
        status=FixStatus.delivered,
        pr_id=pr.id,
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
    db.refresh(pr)
    assert pr.pr_state == "closed"
    # P1: a delivered fix whose PR closed without merging is withdrawn so a
    # later reopen can restore it (mirrors the ready-stage delivery guard).
    db.refresh(fix)
    assert fix.status == FixStatus.superseded_by_closed_pr


def test_github_webhook_pull_request_reopened_updates_fix(
    client: TestClient,
    db: Session,
    org: Organization,
) -> None:
    repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"owner/pr-reopen-{uuid.uuid4().hex[:6]}",
        installation_id=99912,
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
        message="test issue reopened",
    )
    db.add(issue)
    db.commit()
    db.refresh(issue)

    pr_url = f"https://github.com/owner/repo/pull/{uuid.uuid4().int % 10**9}"
    pr = PullRequest(
        repo_id=repo.id,
        pr_branch="greensecops/fix-test-reopen",
        pr_url=pr_url,
        pr_state="closed",
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)
    fix = Fix(
        workflow_file_id=wf.id,
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o-mini",
        status=FixStatus.delivered,
        pr_id=pr.id,
    )
    db.add(fix)
    db.commit()
    db.refresh(fix)

    payload = {
        "action": "reopened",
        "pull_request": {"html_url": pr_url},
    }

    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-GitHub-Event": "pull_request"},
        )

    assert response.status_code == 200
    db.refresh(pr)
    assert pr.pr_state == "open"
    # A delivered fix keeps its status on reopen — its content is in the PR.
    db.refresh(fix)
    assert fix.status == FixStatus.delivered


def test_github_webhook_pull_request_reopened_restores_guard_rejected_fix(
    client: TestClient,
    db: Session,
    org: Organization,
) -> None:
    """Fixes auto-rejected by the closed-PR delivery guard (rejected, never
    delivered) become ready again when the PR is reopened on GitHub."""
    repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"owner/pr-restore-{uuid.uuid4().hex[:6]}",
        installation_id=99913,
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

    pr_url = f"https://github.com/owner/repo/pull/{uuid.uuid4().int % 10**9}"
    pr = PullRequest(
        repo_id=repo.id,
        pr_branch="greensecops/fix-test-restore",
        pr_url=pr_url,
        pr_state="closed",
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)
    fix = Fix(
        workflow_file_id=wf.id,
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o-mini",
        status=FixStatus.superseded_by_closed_pr,
        pr_id=pr.id,
        full_content="on: push\njobs: {}",
    )
    db.add(fix)
    db.commit()
    db.refresh(fix)
    assert fix.delivered_at is None

    payload = {
        "action": "reopened",
        "pull_request": {"html_url": pr_url},
    }

    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-GitHub-Event": "pull_request"},
        )

    assert response.status_code == 200
    db.refresh(pr)
    assert pr.pr_state == "open"
    db.refresh(fix)
    assert fix.status == FixStatus.ready


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


def test_github_webhook_pull_request_synchronize_bumps_open_pr(
    client: TestClient,
    db: Session,
    org: Organization,
) -> None:
    """A synchronize event on an open PR is recorded (updated_at) instead of
    being silently ignored, and leaves the PR open."""
    repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"owner/pr-sync-{uuid.uuid4().hex[:6]}",
        installation_id=99914,
        enabled=True,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    pr_url = f"https://github.com/owner/repo/pull/{uuid.uuid4().int % 10**9}"
    pr = PullRequest(
        repo_id=repo.id,
        pr_branch="greensecops/fix-sync",
        pr_url=pr_url,
        pr_state="open",
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)
    assert pr.updated_at is None

    payload = {"action": "synchronize", "pull_request": {"html_url": pr_url}}
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-GitHub-Event": "pull_request"},
        )
    assert response.status_code == 200
    db.refresh(pr)
    assert pr.pr_state == PullRequestState.open
    assert pr.updated_at is not None


def test_github_webhook_pull_request_synchronize_noop_on_closed_pr(
    client: TestClient,
    db: Session,
    org: Organization,
) -> None:
    """A synchronize event on a closed PR is a no-op (no spurious reopen)."""
    repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"owner/pr-sync-closed-{uuid.uuid4().hex[:6]}",
        installation_id=99915,
        enabled=True,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    pr_url = f"https://github.com/owner/repo/pull/{uuid.uuid4().int % 10**9}"
    pr = PullRequest(
        repo_id=repo.id,
        pr_branch="greensecops/fix-sync-closed",
        pr_url=pr_url,
        pr_state="closed",
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)

    payload = {"action": "synchronize", "pull_request": {"html_url": pr_url}}
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-GitHub-Event": "pull_request"},
        )
    assert response.status_code == 200
    db.refresh(pr)
    assert pr.pr_state == PullRequestState.closed


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


@pytest.mark.parametrize(
    ("action", "expected_event"),
    [
        ("deleted", "installation.deleted"),
        ("suspend", "installation.suspended"),
    ],
)
def test_github_webhook_installation_disable_publishes_correct_event(
    client: TestClient,
    db: Session,
    org: Organization,
    action: str,
    expected_event: str,
) -> None:
    installation_id = int(uuid.uuid4().int % 10**6) + 800000
    repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"owner/event-repo-{uuid.uuid4().hex[:6]}",
        installation_id=installation_id,
        enabled=True,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    payload = {"action": action, "installation": {"id": installation_id}}

    with (
        patch.object(settings, "GITHUB_WEBHOOK_SECRET", None),
        patch("app.api.routes.webhooks.events_pub.publish_event") as mock_pub,
    ):
        response = client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-GitHub-Event": "installation"},
        )

    assert response.status_code == 200
    published_events = [call.args[0].event for call in mock_pub.call_args_list]
    assert expected_event in published_events


@pytest.mark.parametrize(
    ("action", "expected_event"),
    [
        ("created", "installation.created"),
        ("unsuspend", "installation.unsuspended"),
        ("new_permissions_accepted", "installation.updated"),
    ],
)
def test_github_webhook_installation_activate_publishes_correct_event(
    client: TestClient,
    db: Session,
    action: str,
    expected_event: str,
) -> None:
    installation_id = int(uuid.uuid4().int % 10**6) + 900000
    account_id = int(uuid.uuid4().int % 10**9)
    login = f"event-acct-{uuid.uuid4().hex[:6]}"
    payload = {
        "action": action,
        "installation": {
            "id": installation_id,
            "account": {"id": account_id, "login": login, "type": "Organization"},
        },
    }

    with (
        patch.object(settings, "GITHUB_WEBHOOK_SECRET", None),
        patch("app.api.routes.webhooks._enqueue_installation_sync"),
        patch("app.api.routes.webhooks.events_pub.publish_event") as mock_pub,
    ):
        response = client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-GitHub-Event": "installation"},
        )

    assert response.status_code == 200
    published_events = [call.args[0].event for call in mock_pub.call_args_list]
    assert expected_event in published_events


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

    mock_redis = MagicMock()
    mock_redis.set.return_value = True  # NX succeeds → first caller
    mock_task = MagicMock()
    with (
        patch("redis.Redis.from_url", return_value=mock_redis),
        patch(
            "app.workers.tasks.installation_sync.sync_installation_repositories",
            mock_task,
        ),
    ):
        _enqueue_installation_sync(12345, "org-id-str")
    mock_task.delay.assert_called_once()


def test_enqueue_installation_sync_deduplicates() -> None:
    """Second call with same installation_id within TTL window must be silently skipped."""
    from unittest.mock import MagicMock

    from app.api.routes.webhooks import _enqueue_installation_sync

    mock_redis = MagicMock()
    mock_redis.set.return_value = None  # NX fails → already queued
    mock_task = MagicMock()
    with (
        patch("redis.Redis.from_url", return_value=mock_redis),
        patch(
            "app.workers.tasks.installation_sync.sync_installation_repositories",
            mock_task,
        ),
    ):
        _enqueue_installation_sync(12345, "org-id-str")
    mock_task.delay.assert_not_called()


def test_enqueue_installation_sync_fails_open_on_redis_error() -> None:
    """Redis error must not prevent the sync task from being enqueued."""
    from unittest.mock import MagicMock

    from app.api.routes.webhooks import _enqueue_installation_sync

    mock_task = MagicMock()
    with (
        patch("redis.Redis.from_url", side_effect=RuntimeError("redis down")),
        patch(
            "app.workers.tasks.installation_sync.sync_installation_repositories",
            mock_task,
        ),
    ):
        _enqueue_installation_sync(99999, "org-id-str")
    mock_task.delay.assert_called_once()


# ─── Repository event ─────────────────────────────────────────────────────────


def test_github_webhook_repository_renamed_updates_full_name(
    client: TestClient, db: Session, enabled_repo: Repository
) -> None:
    new_name = f"owner/renamed-{uuid.uuid4().hex[:8]}"
    payload = {
        "action": "renamed",
        "repository": {
            "id": enabled_repo.github_repo_id,
            "full_name": new_name,
            "default_branch": "main",
        },
    }
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(
            WEBHOOK_URL, json=payload, headers={"X-GitHub-Event": "repository"}
        )

    assert response.status_code == 200
    db.refresh(enabled_repo)
    assert enabled_repo.full_name == new_name


def test_github_webhook_repository_default_branch_change(
    client: TestClient, db: Session, enabled_repo: Repository
) -> None:
    payload = {
        "action": "edited",
        "changes": {"default_branch": {"from": "main"}},
        "repository": {
            "id": enabled_repo.github_repo_id,
            "full_name": enabled_repo.full_name,
            "default_branch": "develop",
        },
    }
    with (
        patch.object(settings, "GITHUB_WEBHOOK_SECRET", None),
        # The handler now enqueues an analysis of the new default branch;
        # patched so the test stays hermetic (no Celery broker in CI).
        patch("app.api.routes.webhooks._enqueue_static_analysis"),
    ):
        response = client.post(
            WEBHOOK_URL, json=payload, headers={"X-GitHub-Event": "repository"}
        )

    assert response.status_code == 200
    db.refresh(enabled_repo)
    assert enabled_repo.default_branch == "develop"


def test_github_webhook_repository_deleted_disables_repo(
    client: TestClient, db: Session, enabled_repo: Repository
) -> None:
    payload = {
        "action": "deleted",
        "repository": {
            "id": enabled_repo.github_repo_id,
            "full_name": enabled_repo.full_name,
        },
    }
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(
            WEBHOOK_URL, json=payload, headers={"X-GitHub-Event": "repository"}
        )

    assert response.status_code == 200
    db.refresh(enabled_repo)
    assert enabled_repo.enabled is False


def test_github_webhook_repository_archived_disables_and_unarchived_reenables(
    client: TestClient, db: Session, enabled_repo: Repository
) -> None:
    base = {
        "repository": {
            "id": enabled_repo.github_repo_id,
            "full_name": enabled_repo.full_name,
        },
    }
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        client.post(
            WEBHOOK_URL,
            json={"action": "archived", **base},
            headers={"X-GitHub-Event": "repository"},
        )
        db.refresh(enabled_repo)
        assert enabled_repo.enabled is False

        client.post(
            WEBHOOK_URL,
            json={"action": "unarchived", **base},
            headers={"X-GitHub-Event": "repository"},
        )
        db.refresh(enabled_repo)
        assert enabled_repo.enabled is True


def test_github_webhook_repository_unknown_repo_skipped(client: TestClient) -> None:
    payload = {
        "action": "renamed",
        "repository": {"id": 987654321, "full_name": "ghost/repo"},
    }
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(
            WEBHOOK_URL, json=payload, headers={"X-GitHub-Event": "repository"}
        )
    assert response.status_code == 200


# ─── /greensecops commands ────────────────────────────────────────────────────


def test_github_webhook_reanalyze_command_enqueues_forced_analysis(
    client: TestClient, enabled_repo: Repository
) -> None:
    payload = {
        "action": "created",
        "comment": {"body": "/greensecops reanalyze"},
        "repository": {"id": enabled_repo.github_repo_id},
    }
    with (
        patch.object(settings, "GITHUB_WEBHOOK_SECRET", None),
        patch("app.api.routes.webhooks._enqueue_static_analysis") as enqueue,
    ):
        response = client.post(
            WEBHOOK_URL, json=payload, headers={"X-GitHub-Event": "issue_comment"}
        )

    assert response.status_code == 200
    enqueue.assert_called_once()
    assert enqueue.call_args.kwargs["repo_id"] == str(enabled_repo.id)
    assert enqueue.call_args.kwargs["force"] is True


def test_github_webhook_ignore_command_mutes_issue_by_fingerprint(
    client: TestClient, db: Session, enabled_repo: Repository
) -> None:
    analysis = Analysis(
        repo_id=enabled_repo.id,
        content_hash=uuid.uuid4().hex,
        status=AnalysisStatus.completed,
        triggered_by=AnalysisTrigger.manual,
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    rule = db.exec(select(Rule)).first()
    assert rule is not None
    fingerprint = uuid.uuid4().hex[:16]
    issue = Issue(
        analysis_id=analysis.id,
        rule_id=rule.id,
        severity=IssueSeverity.high,
        category=IssueCategory.security,
        message="mute me",
        fingerprint=fingerprint,
    )
    db.add(issue)
    db.commit()
    db.refresh(issue)
    assert issue.status == IssueStatus.open

    payload = {
        "action": "created",
        "comment": {"body": f"/greensecops ignore {fingerprint}"},
        "repository": {"id": enabled_repo.github_repo_id},
    }
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(
            WEBHOOK_URL, json=payload, headers={"X-GitHub-Event": "issue_comment"}
        )
    assert response.status_code == 200
    db.refresh(issue)
    assert issue.ignored_at is not None
    assert issue.status == IssueStatus.ignored

    # `unignore` reverses it.
    payload["comment"]["body"] = f"/greensecops unignore {fingerprint}"
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(
            WEBHOOK_URL, json=payload, headers={"X-GitHub-Event": "issue_comment"}
        )
    assert response.status_code == 200
    db.refresh(issue)
    assert issue.ignored_at is None
    assert issue.status == IssueStatus.open


def test_github_webhook_unknown_command_is_ignored(
    client: TestClient, enabled_repo: Repository
) -> None:
    payload = {
        "action": "created",
        "comment": {"body": "/greensecops do-something-else"},
        "repository": {"id": enabled_repo.github_repo_id},
    }
    with (
        patch.object(settings, "GITHUB_WEBHOOK_SECRET", None),
        patch("app.api.routes.webhooks._enqueue_static_analysis") as enqueue,
    ):
        response = client.post(
            WEBHOOK_URL, json=payload, headers={"X-GitHub-Event": "issue_comment"}
        )

    assert response.status_code == 200
    enqueue.assert_not_called()


# ─── Delivery dedup ───────────────────────────────────────────────────────────


def test_github_webhook_duplicate_delivery_skipped(client: TestClient) -> None:
    from unittest.mock import AsyncMock

    with (
        patch.object(settings, "GITHUB_WEBHOOK_SECRET", None),
        patch(
            "app.api.routes.webhooks._is_duplicate_delivery",
            new=AsyncMock(return_value=True),
        ),
    ):
        response = client.post(
            WEBHOOK_URL,
            json={"action": "created"},
            headers={
                "X-GitHub-Event": "push",
                "X-GitHub-Delivery": "dup-delivery-id",
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "duplicate"


def test_is_duplicate_delivery_without_id_is_false() -> None:
    import asyncio

    from app.api.routes.webhooks import _is_duplicate_delivery

    assert asyncio.run(_is_duplicate_delivery(None)) is False
    assert asyncio.run(_is_duplicate_delivery("")) is False


def test_is_duplicate_delivery_uses_redis_setnx() -> None:
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from app.api.routes.webhooks import _is_duplicate_delivery

    fake_redis = MagicMock()
    fake_redis.aclose = AsyncMock()

    # Fresh delivery: SET NX succeeds → not a duplicate
    fake_redis.set = AsyncMock(return_value=True)
    with patch("redis.asyncio.from_url", return_value=fake_redis):
        assert asyncio.run(_is_duplicate_delivery("delivery-1")) is False

    # Redelivery: SET NX fails → duplicate
    fake_redis.set = AsyncMock(return_value=None)
    with patch("redis.asyncio.from_url", return_value=fake_redis):
        assert asyncio.run(_is_duplicate_delivery("delivery-1")) is True
    fake_redis.aclose.assert_awaited()


def test_is_duplicate_delivery_fails_open_on_redis_error() -> None:
    import asyncio

    from app.api.routes.webhooks import _is_duplicate_delivery

    with patch("redis.asyncio.from_url", side_effect=RuntimeError("redis down")):
        assert asyncio.run(_is_duplicate_delivery("delivery-2")) is False


# ─── PR draft / CI / review attributes ────────────────────────────────────────


def _make_repo_with_open_pr(db: Session, org: Organization, branch: str) -> PullRequest:
    repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"owner/attr-{uuid.uuid4().hex[:6]}",
        installation_id=int(uuid.uuid4().int % 10**8),
        enabled=True,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    pr = PullRequest(
        repo_id=repo.id,
        pr_branch=branch,
        pr_url=f"https://github.com/owner/repo/pull/{uuid.uuid4().int % 10**9}",
        pr_state="open",
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)
    return pr


def test_github_webhook_pr_draft_toggle(
    client: TestClient, db: Session, org: Organization
) -> None:
    pr = _make_repo_with_open_pr(db, org, "greensecops/draft-toggle")
    for action, expected in (
        ("converted_to_draft", PullRequestState.draft),
        ("ready_for_review", PullRequestState.open),
    ):
        payload = {"action": action, "pull_request": {"html_url": pr.pr_url}}
        with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
            resp = client.post(
                WEBHOOK_URL, json=payload, headers={"X-GitHub-Event": "pull_request"}
            )
        assert resp.status_code == 200
        db.refresh(pr)
        assert pr.pr_state == expected


def test_github_webhook_check_suite_sets_ci_status(
    client: TestClient, db: Session, org: Organization
) -> None:
    pr = _make_repo_with_open_pr(db, org, "greensecops/ci-branch")
    repo = db.get(Repository, pr.repo_id)
    payload = {
        "action": "completed",
        "check_suite": {
            "head_branch": pr.pr_branch,
            "status": "completed",
            "conclusion": "failure",
        },
        "repository": {"id": repo.github_repo_id},
    }
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        resp = client.post(
            WEBHOOK_URL, json=payload, headers={"X-GitHub-Event": "check_suite"}
        )
    assert resp.status_code == 200
    db.refresh(pr)
    assert pr.ci_status == CIStatus.failure


def test_github_webhook_pull_request_review_sets_decision(
    client: TestClient, db: Session, org: Organization
) -> None:
    pr = _make_repo_with_open_pr(db, org, "greensecops/review-branch")
    payload = {
        "action": "submitted",
        "review": {"state": "changes_requested"},
        "pull_request": {"html_url": pr.pr_url},
    }
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        resp = client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-GitHub-Event": "pull_request_review"},
        )
    assert resp.status_code == 200
    db.refresh(pr)
    assert pr.review_decision == ReviewDecision.changes_requested


# ─── Repository lifecycle machine ─────────────────────────────────────────────


def test_github_webhook_repository_archived_and_unarchived(
    client: TestClient, db: Session, org: Organization
) -> None:
    repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"owner/arch-{uuid.uuid4().hex[:6]}",
        installation_id=int(uuid.uuid4().int % 10**8),
        enabled=True,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    def _send(action: str) -> None:
        payload = {"action": action, "repository": {"id": repo.github_repo_id}}
        with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
            resp = client.post(
                WEBHOOK_URL, json=payload, headers={"X-GitHub-Event": "repository"}
            )
        assert resp.status_code == 200

    _send("archived")
    db.refresh(repo)
    assert repo.status == RepositoryStatus.archived
    assert repo.is_accessible is False
    assert repo.enabled is False

    _send("unarchived")
    db.refresh(repo)
    assert repo.status == RepositoryStatus.active
    assert repo.is_accessible is True


def test_github_webhook_installation_suspend_unsuspend(
    client: TestClient, db: Session, org: Organization
) -> None:
    installation_id = int(uuid.uuid4().int % 10**8)
    repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"owner/susp-{uuid.uuid4().hex[:6]}",
        installation_id=installation_id,
        enabled=True,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    # unsuspend upserts the org from the installation payload, so it needs
    # account info; suspend does not.
    account = {
        "id": int(uuid.uuid4().int % 10**8),
        "login": f"acct-{uuid.uuid4().hex[:6]}",
    }

    def _send(action: str) -> None:
        payload = {
            "action": action,
            "installation": {"id": installation_id, "account": account},
        }
        with (
            patch.object(settings, "GITHUB_WEBHOOK_SECRET", None),
            patch("app.api.routes.webhooks._enqueue_installation_sync"),
        ):
            resp = client.post(
                WEBHOOK_URL, json=payload, headers={"X-GitHub-Event": "installation"}
            )
        assert resp.status_code == 200

    _send("suspend")
    db.refresh(repo)
    assert repo.status == RepositoryStatus.suspended
    assert repo.is_accessible is False

    _send("unsuspend")
    db.refresh(repo)
    assert repo.status == RepositoryStatus.active
    assert repo.is_accessible is True


# ─── delete (branch) webhook ─────────────────────────────────────────────────


def _seed_branch_issue(
    db: Session, repo: Repository, branch: str, path: str = ".github/workflows/ci.yml"
) -> tuple[WorkflowFile, Issue]:
    wf = WorkflowFile(
        repo_id=repo.id,
        branch=branch,
        path=path,
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
        branch=branch,
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    rule = db.exec(select(Rule)).first()
    assert rule is not None
    issue = Issue(
        analysis_id=analysis.id,
        workflow_file_id=wf.id,
        rule_id=rule.id,
        severity=IssueSeverity.high,
        category=IssueCategory.security,
        message=f"issue on {branch}",
        fingerprint=uuid.uuid4().hex[:16],
    )
    db.add(issue)
    db.commit()
    db.refresh(issue)
    return wf, issue


def _post_delete_event(
    client: TestClient, repo: Repository, ref: str, ref_type: str = "branch"
):  # type: ignore[no-untyped-def]
    payload = {
        "ref": ref,
        "ref_type": ref_type,
        "repository": {"id": repo.github_repo_id},
    }
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        return client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-GitHub-Event": "delete"},
        )


def test_delete_branch_resolves_only_that_branchs_issues(
    client: TestClient,
    db: Session,
    enabled_repo: Repository,
) -> None:
    _main_wf, main_issue = _seed_branch_issue(db, enabled_repo, "main")
    _feat_wf, feat_issue = _seed_branch_issue(db, enabled_repo, "feature")

    response = _post_delete_event(client, enabled_repo, "feature")

    assert response.status_code == 200
    db.refresh(feat_issue)
    assert feat_issue.resolved_at is not None
    assert feat_issue.resolution_reason == IssueResolutionReason.branch_deleted
    assert feat_issue.status == IssueStatus.resolved
    # Default-branch issues untouched.
    db.refresh(main_issue)
    assert main_issue.resolved_at is None

    # Redelivery is idempotent (no error, nothing re-resolved).
    redelivery = _post_delete_event(client, enabled_repo, "feature")
    assert redelivery.status_code == 200


def test_delete_default_branch_is_ignored(
    client: TestClient,
    db: Session,
    enabled_repo: Repository,
) -> None:
    _wf, issue = _seed_branch_issue(db, enabled_repo, "main")
    response = _post_delete_event(client, enabled_repo, "main")
    assert response.status_code == 200
    db.refresh(issue)
    assert issue.resolved_at is None


def test_delete_tag_is_ignored(
    client: TestClient,
    db: Session,
    enabled_repo: Repository,
) -> None:
    _wf, issue = _seed_branch_issue(db, enabled_repo, "v1-branch")
    response = _post_delete_event(client, enabled_repo, "v1-branch", ref_type="tag")
    assert response.status_code == 200
    db.refresh(issue)
    assert issue.resolved_at is None


def test_delete_greensecops_branch_closes_pr_and_supersedes_fix(
    client: TestClient,
    db: Session,
    enabled_repo: Repository,
) -> None:
    wf, _issue = _seed_branch_issue(db, enabled_repo, "main")
    pr = PullRequest(
        repo_id=enabled_repo.id,
        pr_branch="greensecops/fix-abc123",
        pr_url=f"https://github.com/{enabled_repo.full_name}/pull/42",
        pr_state="open",
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)
    fix = Fix(
        workflow_file_id=wf.id,
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o-mini",
        status=FixStatus.delivered,
        pr_id=pr.id,
    )
    db.add(fix)
    db.commit()
    db.refresh(fix)

    response = _post_delete_event(client, enabled_repo, "greensecops/fix-abc123")

    assert response.status_code == 200
    db.refresh(pr)
    assert pr.pr_state == PullRequestState.closed
    db.refresh(fix)
    assert fix.status == FixStatus.superseded_by_closed_pr

    # Redelivery: close is a no-op on an already-closed PR.
    redelivery = _post_delete_event(client, enabled_repo, "greensecops/fix-abc123")
    assert redelivery.status_code == 200
    db.refresh(pr)
    assert pr.pr_state == PullRequestState.closed


def test_push_with_deleted_flag_is_ignored(
    client: TestClient,
    db: Session,
    enabled_repo: Repository,
) -> None:
    payload = {
        "ref": "refs/heads/feature",
        "before": "a" * 40,
        "after": "0" * 40,
        "deleted": True,
        "commits": [],
        "repository": {"id": enabled_repo.github_repo_id},
    }
    with (
        patch.object(settings, "GITHUB_WEBHOOK_SECRET", None),
        patch("app.api.routes.webhooks._enqueue_static_analysis") as mock_enqueue,
    ):
        response = client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-GitHub-Event": "push"},
        )
    assert response.status_code == 200
    mock_enqueue.assert_not_called()


# ─── forced push / default-branch change / PR opened ─────────────────────────


def test_forced_push_without_workflow_commits_triggers_analysis(
    client: TestClient,
    db: Session,  # noqa: ARG001
    enabled_repo: Repository,
) -> None:
    """A rebase can drop workflow changes without listing workflow paths in
    the push commits — forced pushes re-analyse unconditionally."""
    payload = {
        "ref": "refs/heads/feature",
        "before": "a" * 40,
        "after": "b" * 40,
        "forced": True,
        "commits": [{"added": [], "modified": ["src/app.py"], "removed": []}],
        "repository": {"id": enabled_repo.github_repo_id},
    }
    with (
        patch.object(settings, "GITHUB_WEBHOOK_SECRET", None),
        patch("app.api.routes.webhooks._enqueue_static_analysis") as mock_enqueue,
    ):
        response = client.post(
            WEBHOOK_URL, json=payload, headers={"X-GitHub-Event": "push"}
        )
    assert response.status_code == 200
    mock_enqueue.assert_called_once()
    assert mock_enqueue.call_args.kwargs["branch"] == "feature"


def test_unforced_push_without_workflow_commits_still_ignored(
    client: TestClient,
    db: Session,  # noqa: ARG001
    enabled_repo: Repository,
) -> None:
    payload = {
        "ref": "refs/heads/feature",
        "before": "a" * 40,
        "after": "b" * 40,
        "forced": False,
        "commits": [{"added": [], "modified": ["src/app.py"], "removed": []}],
        "repository": {"id": enabled_repo.github_repo_id},
    }
    with (
        patch.object(settings, "GITHUB_WEBHOOK_SECRET", None),
        patch("app.api.routes.webhooks._enqueue_static_analysis") as mock_enqueue,
    ):
        response = client.post(
            WEBHOOK_URL, json=payload, headers={"X-GitHub-Event": "push"}
        )
    assert response.status_code == 200
    mock_enqueue.assert_not_called()


def test_default_branch_change_triggers_analysis_of_new_branch(
    client: TestClient,
    db: Session,
    enabled_repo: Repository,
) -> None:
    payload = {
        "action": "edited",
        "repository": {
            "id": enabled_repo.github_repo_id,
            "full_name": enabled_repo.full_name,
            "default_branch": "develop",
        },
    }
    with (
        patch.object(settings, "GITHUB_WEBHOOK_SECRET", None),
        patch("app.api.routes.webhooks._enqueue_static_analysis") as mock_enqueue,
    ):
        response = client.post(
            WEBHOOK_URL, json=payload, headers={"X-GitHub-Event": "repository"}
        )
    assert response.status_code == 200
    db.refresh(enabled_repo)
    assert enabled_repo.default_branch == "develop"
    mock_enqueue.assert_called_once()
    assert mock_enqueue.call_args.kwargs["branch"] == "develop"


def test_default_branch_change_disabled_repo_no_analysis(
    client: TestClient,
    db: Session,
    disabled_repo: Repository,
) -> None:
    payload = {
        "action": "edited",
        "repository": {
            "id": disabled_repo.github_repo_id,
            "full_name": disabled_repo.full_name,
            "default_branch": "develop",
        },
    }
    with (
        patch.object(settings, "GITHUB_WEBHOOK_SECRET", None),
        patch("app.api.routes.webhooks._enqueue_static_analysis") as mock_enqueue,
    ):
        response = client.post(
            WEBHOOK_URL, json=payload, headers={"X-GitHub-Event": "repository"}
        )
    assert response.status_code == 200
    db.refresh(disabled_repo)
    assert disabled_repo.default_branch == "develop"  # still synced
    mock_enqueue.assert_not_called()


def test_pull_request_opened_from_fix_branch_creates_record(
    client: TestClient,
    db: Session,
    enabled_repo: Repository,
) -> None:
    pr_url = f"https://github.com/{enabled_repo.full_name}/pull/77"
    payload = {
        "action": "opened",
        "pull_request": {
            "html_url": pr_url,
            "head": {"ref": "greensecops/fix-manual"},
        },
        "repository": {"id": enabled_repo.github_repo_id},
    }
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(
            WEBHOOK_URL, json=payload, headers={"X-GitHub-Event": "pull_request"}
        )
    assert response.status_code == 200
    pr_record = db.exec(
        select(PullRequest)
        .where(PullRequest.repo_id == enabled_repo.id)
        .where(PullRequest.pr_branch == "greensecops/fix-manual")
    ).one()
    assert pr_record.pr_url == pr_url
    assert pr_record.pr_state == PullRequestState.open


def test_pull_request_opened_reopens_closed_record(
    client: TestClient,
    db: Session,
    enabled_repo: Repository,
) -> None:
    pr_record = PullRequest(
        repo_id=enabled_repo.id,
        pr_branch="greensecops/fix-was-closed",
        pr_url=None,
        pr_state=PullRequestState.closed,
    )
    db.add(pr_record)
    db.commit()
    db.refresh(pr_record)

    pr_url = f"https://github.com/{enabled_repo.full_name}/pull/78"
    payload = {
        "action": "opened",
        "pull_request": {
            "html_url": pr_url,
            "head": {"ref": "greensecops/fix-was-closed"},
        },
        "repository": {"id": enabled_repo.github_repo_id},
    }
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(
            WEBHOOK_URL, json=payload, headers={"X-GitHub-Event": "pull_request"}
        )
    assert response.status_code == 200
    db.refresh(pr_record)
    assert pr_record.pr_state == PullRequestState.open
    assert pr_record.pr_url == pr_url


def test_pull_request_opened_from_user_branch_ignored(
    client: TestClient,
    db: Session,
    enabled_repo: Repository,
) -> None:
    payload = {
        "action": "opened",
        "pull_request": {
            "html_url": f"https://github.com/{enabled_repo.full_name}/pull/79",
            "head": {"ref": "feature/user-branch"},
        },
        "repository": {"id": enabled_repo.github_repo_id},
    }
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        response = client.post(
            WEBHOOK_URL, json=payload, headers={"X-GitHub-Event": "pull_request"}
        )
    assert response.status_code == 200
    assert (
        db.exec(
            select(PullRequest).where(PullRequest.repo_id == enabled_repo.id)
        ).first()
        is None
    )


# ─── externally_modified fix branches ────────────────────────────────────────


def _post_push_to_fix_branch(client: TestClient, repo: Repository, sender_login: str):  # type: ignore[no-untyped-def]
    payload = {
        "ref": "refs/heads/greensecops/fixes-abc",
        "before": "a" * 40,
        "after": "b" * 40,
        "commits": [
            {"added": [], "modified": [".github/workflows/ci.yml"], "removed": []}
        ],
        "sender": {"login": sender_login},
        "repository": {"id": repo.github_repo_id},
    }
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        return client.post(
            WEBHOOK_URL, json=payload, headers={"X-GitHub-Event": "push"}
        )


def test_user_push_to_fix_branch_sets_externally_modified(
    client: TestClient,
    db: Session,
    enabled_repo: Repository,
) -> None:
    pr = PullRequest(
        repo_id=enabled_repo.id,
        pr_branch="greensecops/fixes-abc",
        pr_url=f"https://github.com/{enabled_repo.full_name}/pull/91",
        pr_state="open",
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)

    response = _post_push_to_fix_branch(client, enabled_repo, "some-human")

    assert response.status_code == 200
    db.refresh(pr)
    assert pr.externally_modified is True


def test_bot_push_to_fix_branch_does_not_set_externally_modified(
    client: TestClient,
    db: Session,
    enabled_repo: Repository,
) -> None:
    pr = PullRequest(
        repo_id=enabled_repo.id,
        pr_branch="greensecops/fixes-abc",
        pr_url=f"https://github.com/{enabled_repo.full_name}/pull/92",
        pr_state="open",
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)

    bot_login = settings.GITHUB_BOT_HANDLE.lstrip("@") + "[bot]"
    response = _post_push_to_fix_branch(client, enabled_repo, bot_login)

    assert response.status_code == 200
    db.refresh(pr)
    assert pr.externally_modified is False


def test_push_to_fix_branch_never_enqueues_analysis(
    client: TestClient,
    db: Session,  # noqa: ARG001
    enabled_repo: Repository,
) -> None:
    with patch("app.api.routes.webhooks._enqueue_static_analysis") as mock_enqueue:
        response = _post_push_to_fix_branch(client, enabled_repo, "some-human")
    assert response.status_code == 200
    mock_enqueue.assert_not_called()


def test_default_branch_push_enqueues_mergeable_refresh(
    client: TestClient,
    db: Session,
    enabled_repo: Repository,
) -> None:
    pr = PullRequest(
        repo_id=enabled_repo.id,
        pr_branch="greensecops/fixes-xyz",
        pr_url=f"https://github.com/{enabled_repo.full_name}/pull/93",
        pr_state=PullRequestState.open,
    )
    db.add(pr)
    db.commit()

    payload = {
        "ref": f"refs/heads/{enabled_repo.default_branch}",
        "before": "a" * 40,
        "after": "b" * 40,
        "commits": [{"added": [], "modified": ["README.md"], "removed": []}],
        "repository": {"id": enabled_repo.github_repo_id},
    }
    with (
        patch.object(settings, "GITHUB_WEBHOOK_SECRET", None),
        patch(
            "app.workers.tasks.maintenance.refresh_pr_mergeable_state.delay"
        ) as mock_refresh,
    ):
        response = client.post(
            WEBHOOK_URL, json=payload, headers={"X-GitHub-Event": "push"}
        )
    assert response.status_code == 200
    mock_refresh.assert_called_once_with(repo_id=str(enabled_repo.id))


def test_non_default_branch_push_no_mergeable_refresh(
    client: TestClient,
    db: Session,
    enabled_repo: Repository,
) -> None:
    pr = PullRequest(
        repo_id=enabled_repo.id,
        pr_branch="greensecops/fixes-xyz",
        pr_url=f"https://github.com/{enabled_repo.full_name}/pull/94",
        pr_state=PullRequestState.open,
    )
    db.add(pr)
    db.commit()

    payload = {
        "ref": "refs/heads/feature",
        "before": "a" * 40,
        "after": "b" * 40,
        "commits": [{"added": [], "modified": ["README.md"], "removed": []}],
        "repository": {"id": enabled_repo.github_repo_id},
    }
    with (
        patch.object(settings, "GITHUB_WEBHOOK_SECRET", None),
        patch(
            "app.workers.tasks.maintenance.refresh_pr_mergeable_state.delay"
        ) as mock_refresh,
    ):
        response = client.post(
            WEBHOOK_URL, json=payload, headers={"X-GitHub-Event": "push"}
        )
    assert response.status_code == 200
    mock_refresh.assert_not_called()


def test_default_branch_push_without_open_pr_no_refresh(
    client: TestClient,
    db: Session,  # noqa: ARG001
    enabled_repo: Repository,
) -> None:
    payload = {
        "ref": f"refs/heads/{enabled_repo.default_branch}",
        "before": "a" * 40,
        "after": "b" * 40,
        "commits": [{"added": [], "modified": ["README.md"], "removed": []}],
        "repository": {"id": enabled_repo.github_repo_id},
    }
    with (
        patch.object(settings, "GITHUB_WEBHOOK_SECRET", None),
        patch(
            "app.workers.tasks.maintenance.refresh_pr_mergeable_state.delay"
        ) as mock_refresh,
    ):
        response = client.post(
            WEBHOOK_URL, json=payload, headers={"X-GitHub-Event": "push"}
        )
    assert response.status_code == 200
    mock_refresh.assert_not_called()
