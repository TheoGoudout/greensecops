"""Tests for the /api/v1/issues/ endpoints."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    Analysis,
    AnalysisStatus,
    AnalysisTrigger,
    Issue,
    IssueCategory,
    IssueSeverity,
    IssueStatus,
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
        name=f"issues-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free
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
        full_name=f"issuesowner/repo-{uuid.uuid4().hex[:8]}",
        installation_id=77777,
    )
    db.add(repository)
    db.commit()
    db.refresh(repository)
    return repository


@pytest.fixture()
def workflow_file(db: Session, repo: Repository) -> WorkflowFile:
    wf = WorkflowFile(
        repo_id=repo.id,
        path=".github/workflows/issues-test.yml",
        content_hash=uuid.uuid4().hex,
        raw_content="on: push\njobs: {}",
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


@pytest.fixture()
def analysis(db: Session, repo: Repository, workflow_file: WorkflowFile) -> Analysis:
    from datetime import datetime, timezone

    a = Analysis(
        repo_id=repo.id,
        workflow_file_id=workflow_file.id,
        content_hash=workflow_file.content_hash,
        status=AnalysisStatus.completed,
        score=75.0,
        grade="C",
        triggered_by=AnalysisTrigger.manual,
        branch="main",
        completed_at=datetime.now(timezone.utc),
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


@pytest.fixture()
def rule(db: Session) -> Rule:
    r = Rule(
        slug=f"test-issues-rule-{uuid.uuid4().hex[:8]}",
        category=IssueCategory.security,
        severity=IssueSeverity.high,
        title="Test Issues Rule",
        description="A test rule for issues tests",
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
        severity=IssueSeverity.high,
        category=IssueCategory.security,
        line_start=10,
        line_end=12,
        message="Test security issue",
        context='{"step": "test"}',
    )
    db.add(i)
    db.commit()
    db.refresh(i)
    return i


# ─── GET /issues/ ─────────────────────────────────────────────────────────────


def test_list_issues_empty(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    # Arrange — fresh analysis with no issues
    fresh_org = Organization(
        name=f"empty-issues-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free
    )
    db.add(fresh_org)
    db.commit()
    db.refresh(fresh_org)

    fresh_repo = Repository(
        org_id=fresh_org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"empty-issues/repo-{uuid.uuid4().hex[:8]}",
        installation_id=88888,
    )
    db.add(fresh_repo)
    db.commit()
    db.refresh(fresh_repo)

    fresh_wf = WorkflowFile(
        repo_id=fresh_repo.id,
        path=".github/workflows/empty.yml",
        content_hash=uuid.uuid4().hex,
        raw_content="on: push\njobs: {}",
    )
    db.add(fresh_wf)
    db.commit()
    db.refresh(fresh_wf)

    fresh_analysis = Analysis(
        repo_id=fresh_repo.id,
        workflow_file_id=fresh_wf.id,
        content_hash=fresh_wf.content_hash,
        status=AnalysisStatus.completed,
        score=100.0,
        grade="A+++",
        triggered_by=AnalysisTrigger.manual,
    )
    db.add(fresh_analysis)
    db.commit()
    db.refresh(fresh_analysis)

    # Act
    response = client.get(
        f"{settings.API_V1_STR}/issues/",
        params={"analysis_id": str(fresh_analysis.id)},
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    assert response.json() == []


def test_list_issues_with_data(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    issue: Issue,
    analysis: Analysis,
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/issues/",
        params={"analysis_id": str(analysis.id)},
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    ids = [i["id"] for i in data]
    assert str(issue.id) in ids


def test_list_issues_filter_by_category(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    issue: Issue,
    analysis: Analysis,
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/issues/",
        params={"analysis_id": str(analysis.id), "category": "security"},
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert all(i["category"] == "security" for i in data)
    assert any(i["id"] == str(issue.id) for i in data)


def test_list_issues_filter_by_severity(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    issue: Issue,
    analysis: Analysis,
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/issues/",
        params={"analysis_id": str(analysis.id), "severity": "high"},
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert all(i["severity"] == "high" for i in data)
    assert any(i["id"] == str(issue.id) for i in data)


def test_list_issues_filter_by_repo_id(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    issue: Issue,
    repo: Repository,
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/issues/",
        params={"repo_id": str(repo.id)},
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert any(i["id"] == str(issue.id) for i in data)


def test_list_issues_unfixed_filter(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    issue: Issue,
    analysis: Analysis,
) -> None:
    # Act — issue with no fix should appear when unfixed=true
    response = client.get(
        f"{settings.API_V1_STR}/issues/",
        params={"analysis_id": str(analysis.id), "unfixed": "true"},
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert any(i["id"] == str(issue.id) for i in data)


def test_list_issues_includes_fix_status(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    issue: Issue,
    analysis: Analysis,
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/issues/",
        params={"analysis_id": str(analysis.id)},
        headers=superuser_token_headers,
    )

    # Assert — fix_id and fix_status present (null when no fix exists)
    assert response.status_code == 200
    data = response.json()
    found = next(i for i in data if i["id"] == str(issue.id))
    assert found["fix_id"] is None
    assert found["fix_status"] is None


# ─── GET /issues/{id} ─────────────────────────────────────────────────────────


def test_get_issue_found(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    issue: Issue,
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/issues/{issue.id}",
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(issue.id)
    assert body["message"] == "Test security issue"
    assert body["severity"] == "high"


def test_get_issue_not_found(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/issues/{uuid.uuid4()}",
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 404
    assert response.json()["detail"] == "Issue not found"


def test_list_issues_latest_only_excludes_old_analysis(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    workflow_file: WorkflowFile,
    rule: Rule,
    analysis: Analysis,
    issue: Issue,
) -> None:
    from datetime import datetime, timezone

    # Arrange — create a newer analysis with a later completed_at
    new_analysis = Analysis(
        repo_id=repo.id,
        workflow_file_id=workflow_file.id,
        content_hash=uuid.uuid4().hex,
        status=AnalysisStatus.completed,
        score=90.0,
        grade="A",
        triggered_by=AnalysisTrigger.manual,
        branch="main",
        completed_at=datetime.now(timezone.utc),
    )
    db.add(new_analysis)
    db.commit()
    db.refresh(new_analysis)

    new_issue = Issue(
        analysis_id=new_analysis.id,
        workflow_file_id=new_analysis.workflow_file_id,
        rule_id=rule.id,
        severity=IssueSeverity.high,
        category=IssueCategory.security,
        line_start=5,
        line_end=7,
        message="New analysis issue",
        context=None,
    )
    db.add(new_issue)
    db.commit()

    # Act — default latest_only=True should return only new_issue
    response = client.get(
        f"{settings.API_V1_STR}/issues/",
        params={"repo_id": str(repo.id)},
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    ids = [i["id"] for i in response.json()]
    assert str(new_issue.id) in ids
    assert str(issue.id) not in ids


def test_list_issues_latest_only_false_includes_all(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    workflow_file: WorkflowFile,
    rule: Rule,
    analysis: Analysis,
    issue: Issue,
) -> None:
    from datetime import datetime, timezone

    # Arrange — create a newer analysis with a later completed_at
    new_analysis = Analysis(
        repo_id=repo.id,
        workflow_file_id=workflow_file.id,
        content_hash=uuid.uuid4().hex,
        status=AnalysisStatus.completed,
        score=90.0,
        grade="A",
        triggered_by=AnalysisTrigger.manual,
        branch="main",
        completed_at=datetime.now(timezone.utc),
    )
    db.add(new_analysis)
    db.commit()
    db.refresh(new_analysis)

    new_issue = Issue(
        analysis_id=new_analysis.id,
        workflow_file_id=new_analysis.workflow_file_id,
        rule_id=rule.id,
        severity=IssueSeverity.high,
        category=IssueCategory.security,
        line_start=5,
        line_end=7,
        message="New analysis issue",
        context=None,
    )
    db.add(new_issue)
    db.commit()

    # Act — latest_only=False returns issues from all analyses
    response = client.get(
        f"{settings.API_V1_STR}/issues/",
        params={"repo_id": str(repo.id), "latest_only": "false"},
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    ids = [i["id"] for i in response.json()]
    assert str(new_issue.id) in ids
    assert str(issue.id) in ids


# ─── POST /issues/{id}/ignore & /unignore ─────────────────────────────────────


def test_ignore_and_unignore_issue(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    issue: Issue,
) -> None:
    # Ignore → status becomes ignored (DB trigger) and ignored_at is set.
    resp = client.post(
        f"{settings.API_V1_STR}/issues/{issue.id}/ignore",
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"
    db.refresh(issue)
    assert issue.ignored_at is not None
    assert issue.status is IssueStatus.ignored

    # Ignore again is idempotent.
    resp = client.post(
        f"{settings.API_V1_STR}/issues/{issue.id}/ignore",
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"

    # Unignore → reverts to the underlying (open) state.
    resp = client.post(
        f"{settings.API_V1_STR}/issues/{issue.id}/unignore",
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "open"
    db.refresh(issue)
    assert issue.ignored_at is None


def test_ignored_issue_hidden_by_default_shown_with_flag(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    issue: Issue,
) -> None:
    client.post(
        f"{settings.API_V1_STR}/issues/{issue.id}/ignore",
        headers=superuser_token_headers,
    )
    # Default list excludes ignored issues.
    resp = client.get(
        f"{settings.API_V1_STR}/issues/",
        params={"repo_id": str(repo.id), "latest_only": "false"},
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200
    assert str(issue.id) not in [i["id"] for i in resp.json()]
    # include_ignored=true surfaces it again.
    resp = client.get(
        f"{settings.API_V1_STR}/issues/",
        params={
            "repo_id": str(repo.id),
            "latest_only": "false",
            "include_ignored": "true",
        },
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200
    assert str(issue.id) in [i["id"] for i in resp.json()]


def test_repo_issue_listing_defaults_to_default_branch(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
) -> None:
    """Without an explicit ?branch=, a repo listing shows only default-branch
    issues; feature-branch issues appear when their branch is requested."""
    rule = db.exec(select(Rule)).first()
    assert rule is not None

    def _seed(branch: str, path: str, message: str) -> Issue:
        wf = WorkflowFile(
            repo_id=repo.id,
            branch=branch,
            path=path,
            content_hash=uuid.uuid4().hex,
            raw_content="on: push\njobs: {}",
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
        issue = Issue(
            analysis_id=analysis.id,
            workflow_file_id=wf.id,
            rule_id=rule.id,
            severity=rule.severity,
            category=rule.category,
            message=message,
            fingerprint=uuid.uuid4().hex[:16],
        )
        db.add(issue)
        db.commit()
        return issue

    _seed("main", ".github/workflows/ci.yml", "on main")
    _seed("feature", ".github/workflows/ci.yml", "on feature")

    url = f"{settings.API_V1_STR}/issues/"
    default_listing = client.get(
        url, params={"repo_id": str(repo.id)}, headers=superuser_token_headers
    )
    assert default_listing.status_code == 200
    messages = [i["message"] for i in default_listing.json()]
    assert "on main" in messages
    assert "on feature" not in messages

    feature_listing = client.get(
        url,
        params={"repo_id": str(repo.id), "branch": "feature"},
        headers=superuser_token_headers,
    )
    assert feature_listing.status_code == 200
    feature_messages = [i["message"] for i in feature_listing.json()]
    assert feature_messages == ["on feature"]
