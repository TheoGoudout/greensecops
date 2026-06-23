"""Tests for the /api/v1/issues/ endpoints."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models import (
    Analysis,
    AnalysisStatus,
    AnalysisTrigger,
    Issue,
    IssueCategory,
    IssueSeverity,
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
    a = Analysis(
        repo_id=repo.id,
        workflow_file_id=workflow_file.id,
        content_hash=workflow_file.content_hash,
        status=AnalysisStatus.completed,
        score=75.0,
        grade="C",
        triggered_by=AnalysisTrigger.manual,
        branch="main",
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    workflow_file.latest_analysis_id = a.id
    db.add(workflow_file)
    db.commit()
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
    # Arrange — create a newer analysis and point workflow_file at it
    new_analysis = Analysis(
        repo_id=repo.id,
        workflow_file_id=workflow_file.id,
        content_hash=uuid.uuid4().hex,
        status=AnalysisStatus.completed,
        score=90.0,
        grade="A",
        triggered_by=AnalysisTrigger.manual,
        branch="main",
    )
    db.add(new_analysis)
    db.commit()
    db.refresh(new_analysis)

    new_issue = Issue(
        analysis_id=new_analysis.id,
        rule_id=rule.id,
        severity=IssueSeverity.high,
        category=IssueCategory.security,
        line_start=5,
        line_end=7,
        message="New analysis issue",
        context=None,
    )
    db.add(new_issue)

    workflow_file.latest_analysis_id = new_analysis.id
    db.add(workflow_file)
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
    # Arrange — create a newer analysis pointing workflow_file forward
    new_analysis = Analysis(
        repo_id=repo.id,
        workflow_file_id=workflow_file.id,
        content_hash=uuid.uuid4().hex,
        status=AnalysisStatus.completed,
        score=90.0,
        grade="A",
        triggered_by=AnalysisTrigger.manual,
        branch="main",
    )
    db.add(new_analysis)
    db.commit()
    db.refresh(new_analysis)

    new_issue = Issue(
        analysis_id=new_analysis.id,
        rule_id=rule.id,
        severity=IssueSeverity.high,
        category=IssueCategory.security,
        line_start=5,
        line_end=7,
        message="New analysis issue",
        context=None,
    )
    db.add(new_issue)

    workflow_file.latest_analysis_id = new_analysis.id
    db.add(workflow_file)
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
