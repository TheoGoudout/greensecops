"""Tests for the /api/v1/issues/ endpoints."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    Category,
    FindingStatus,
    Organization,
    Repository,
    Rule,
    ScanStatus,
    ScanTrigger,
    Severity,
    UserTier,
    WorkflowFile,
    WorkflowFinding,
    WorkflowScan,
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
def analysis(
    db: Session, repo: Repository, workflow_file: WorkflowFile
) -> WorkflowScan:
    from datetime import datetime, timezone

    a = WorkflowScan(
        repo_id=repo.id,
        workflow_file_id=workflow_file.id,
        content_hash=workflow_file.content_hash,
        status=ScanStatus.completed,
        score=75.0,
        grade="C",
        triggered_by=ScanTrigger.manual,
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
        category=Category.security,
        severity=Severity.high,
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
def issue(db: Session, analysis: WorkflowScan, rule: Rule) -> WorkflowFinding:
    i = WorkflowFinding(
        analysis_id=analysis.id,
        workflow_file_id=analysis.workflow_file_id,
        rule_id=rule.id,
        severity=Severity.high,
        category=Category.security,
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

    fresh_analysis = WorkflowScan(
        repo_id=fresh_repo.id,
        workflow_file_id=fresh_wf.id,
        content_hash=fresh_wf.content_hash,
        status=ScanStatus.completed,
        score=100.0,
        grade="A+++",
        triggered_by=ScanTrigger.manual,
    )
    db.add(fresh_analysis)
    db.commit()
    db.refresh(fresh_analysis)

    # Act
    response = client.get(
        f"{settings.API_V1_STR}/workflow-findings/",
        params={"analysis_id": str(fresh_analysis.id)},
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    assert response.json() == []


def test_list_issues_with_data(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    issue: WorkflowFinding,
    analysis: WorkflowScan,
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/workflow-findings/",
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
    issue: WorkflowFinding,
    analysis: WorkflowScan,
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/workflow-findings/",
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
    issue: WorkflowFinding,
    analysis: WorkflowScan,
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/workflow-findings/",
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
    issue: WorkflowFinding,
    repo: Repository,
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/workflow-findings/",
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
    issue: WorkflowFinding,
    analysis: WorkflowScan,
) -> None:
    # Act — issue with no fix should appear when unfixed=true
    response = client.get(
        f"{settings.API_V1_STR}/workflow-findings/",
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
    issue: WorkflowFinding,
    analysis: WorkflowScan,
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/workflow-findings/",
        params={"analysis_id": str(analysis.id)},
        headers=superuser_token_headers,
    )

    # Assert — fix_id and fix_status present (null when no fix exists)
    assert response.status_code == 200
    data = response.json()
    found = next(i for i in data if i["id"] == str(issue.id))
    assert found["fix_id"] is None
    assert found["fix_status"] is None


# ─── GET /issues/stats ────────────────────────────────────────────────────────


def test_issue_stats_counts_open_by_category(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    issue: WorkflowFinding,
    repo: Repository,
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/workflow-findings/stats",
        params={"repo_id": str(repo.id)},
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_open"] == 1
    assert body["total_resolved"] == 0
    assert body["critical_open"] == 0
    security = next(c for c in body["by_category"] if c["category"] == "security")
    assert security["open"] == 1
    assert security["resolved"] == 0


def test_issue_stats_counts_critical_separately(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    analysis: WorkflowScan,
    rule: Rule,
    repo: Repository,
) -> None:
    critical_issue = WorkflowFinding(
        analysis_id=analysis.id,
        workflow_file_id=analysis.workflow_file_id,
        rule_id=rule.id,
        severity=Severity.critical,
        category=Category.security,
        message="Critical test issue",
    )
    db.add(critical_issue)
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/workflow-findings/stats",
        params={"repo_id": str(repo.id)},
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["critical_open"] == 1
    assert body["total_open"] == 1


def test_issue_stats_splits_resolved_from_open(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    issue: WorkflowFinding,
    repo: Repository,
) -> None:
    from datetime import datetime, timezone

    issue.resolved_at = datetime.now(timezone.utc)
    db.add(issue)
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/workflow-findings/stats",
        params={"repo_id": str(repo.id)},
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_open"] == 0
    assert body["total_resolved"] == 1


def test_issue_stats_excludes_ignored_issues(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    issue: WorkflowFinding,
    repo: Repository,
) -> None:
    from datetime import datetime, timezone

    issue.ignored_at = datetime.now(timezone.utc)
    db.add(issue)
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/workflow-findings/stats",
        params={"repo_id": str(repo.id)},
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_open"] == 0
    assert body["total_resolved"] == 0
    assert body["by_category"] == []


def test_issue_stats_not_capped_by_pagination(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    analysis: WorkflowScan,
    rule: Rule,
    repo: Repository,
) -> None:
    # Regression guard for the bug this endpoint fixes: a client-side count
    # from a paginated list_issues fetch (limit=200) would silently undercount
    # once an org crosses that many open issues.
    n = 205
    for _ in range(n):
        db.add(
            WorkflowFinding(
                analysis_id=analysis.id,
                workflow_file_id=analysis.workflow_file_id,
                rule_id=rule.id,
                severity=Severity.low,
                category=Category.maintainability,
                message="Bulk stats test issue",
            )
        )
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/workflow-findings/stats",
        params={"repo_id": str(repo.id)},
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_open"] == n


def test_issue_stats_by_repo_breakdown(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    org: Organization,
    repo: Repository,
    issue: WorkflowFinding,
    rule: Rule,
) -> None:
    # `repo`/`issue` fixtures give repo #1 one open `security` issue.
    # Build a second repo with an `energy` issue in a different category.
    other_repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"issuesowner/other-repo-{uuid.uuid4().hex[:8]}",
        installation_id=77778,
    )
    db.add(other_repo)
    db.commit()
    db.refresh(other_repo)

    other_wf = WorkflowFile(
        repo_id=other_repo.id,
        path=".github/workflows/other-issues-test.yml",
        content_hash=uuid.uuid4().hex,
        raw_content="on: push\njobs: {}",
    )
    db.add(other_wf)
    db.commit()
    db.refresh(other_wf)

    other_analysis = WorkflowScan(
        repo_id=other_repo.id,
        workflow_file_id=other_wf.id,
        content_hash=other_wf.content_hash,
        status=ScanStatus.completed,
        score=60.0,
        grade="D",
        triggered_by=ScanTrigger.manual,
        branch="main",
    )
    db.add(other_analysis)
    db.commit()
    db.refresh(other_analysis)

    db.add(
        WorkflowFinding(
            analysis_id=other_analysis.id,
            workflow_file_id=other_wf.id,
            rule_id=rule.id,
            severity=Severity.medium,
            category=Category.energy,
            message="Other repo energy issue",
        )
    )
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/workflow-findings/stats",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    body = response.json()
    by_repo = {r["repo_id"]: r for r in body["by_repo"]}

    repo_stats = by_repo[str(repo.id)]
    assert repo_stats["score"] == 75.0
    assert repo_stats["grade"] == "B"
    repo_categories = {c["category"]: c for c in repo_stats["categories"]}

    repo_security = repo_categories["security"]
    assert repo_security["open"] == 1
    assert repo_security["critical_open"] == 0
    # security carries the repo's only penalty (high, weight 1.0 -> 10.0),
    # so it scores below the repo average while the other 4 (zero-penalty)
    # categories score above it, and the 5 average back to 75.0 exactly.
    assert repo_security["score"] == pytest.approx(67.0)
    assert repo_categories["energy"]["open"] == 0
    assert repo_categories["energy"]["score"] == pytest.approx(77.0)
    scores = [c["score"] for c in repo_categories.values()]
    assert sum(scores) / len(scores) == pytest.approx(repo_stats["score"])

    other_repo_stats = by_repo[str(other_repo.id)]
    assert other_repo_stats["score"] == 60.0
    other_repo_categories = {c["category"]: c for c in other_repo_stats["categories"]}
    assert other_repo_categories["energy"]["open"] == 1
    assert other_repo_categories["security"]["open"] == 0
    other_scores = [c["score"] for c in other_repo_categories.values()]
    assert sum(other_scores) / len(other_scores) == pytest.approx(
        other_repo_stats["score"]
    )


def test_issue_stats_by_repo_empty_when_scoped_to_single_repo(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    issue: WorkflowFinding,
    repo: Repository,
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/workflow-findings/stats",
        params={"repo_id": str(repo.id)},
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    assert response.json()["by_repo"] == []


# ─── GET /issues/{id} ─────────────────────────────────────────────────────────


def test_get_issue_found(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    issue: WorkflowFinding,
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/workflow-findings/{issue.id}",
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
        f"{settings.API_V1_STR}/workflow-findings/{uuid.uuid4()}",
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 404
    assert response.json()["detail"] == "Workflow finding not found"


def test_list_issues_latest_only_excludes_old_analysis(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    workflow_file: WorkflowFile,
    rule: Rule,
    analysis: WorkflowScan,
    issue: WorkflowFinding,
) -> None:
    from datetime import datetime, timezone

    # Arrange — create a newer analysis with a later completed_at
    new_analysis = WorkflowScan(
        repo_id=repo.id,
        workflow_file_id=workflow_file.id,
        content_hash=uuid.uuid4().hex,
        status=ScanStatus.completed,
        score=90.0,
        grade="A",
        triggered_by=ScanTrigger.manual,
        branch="main",
        completed_at=datetime.now(timezone.utc),
    )
    db.add(new_analysis)
    db.commit()
    db.refresh(new_analysis)

    new_issue = WorkflowFinding(
        analysis_id=new_analysis.id,
        workflow_file_id=new_analysis.workflow_file_id,
        rule_id=rule.id,
        severity=Severity.high,
        category=Category.security,
        line_start=5,
        line_end=7,
        message="New analysis issue",
        context=None,
    )
    db.add(new_issue)
    db.commit()

    # Act — default latest_only=True should return only new_issue
    response = client.get(
        f"{settings.API_V1_STR}/workflow-findings/",
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
    analysis: WorkflowScan,
    issue: WorkflowFinding,
) -> None:
    from datetime import datetime, timezone

    # Arrange — create a newer analysis with a later completed_at
    new_analysis = WorkflowScan(
        repo_id=repo.id,
        workflow_file_id=workflow_file.id,
        content_hash=uuid.uuid4().hex,
        status=ScanStatus.completed,
        score=90.0,
        grade="A",
        triggered_by=ScanTrigger.manual,
        branch="main",
        completed_at=datetime.now(timezone.utc),
    )
    db.add(new_analysis)
    db.commit()
    db.refresh(new_analysis)

    new_issue = WorkflowFinding(
        analysis_id=new_analysis.id,
        workflow_file_id=new_analysis.workflow_file_id,
        rule_id=rule.id,
        severity=Severity.high,
        category=Category.security,
        line_start=5,
        line_end=7,
        message="New analysis issue",
        context=None,
    )
    db.add(new_issue)
    db.commit()

    # Act — latest_only=False returns issues from all analyses
    response = client.get(
        f"{settings.API_V1_STR}/workflow-findings/",
        params={"repo_id": str(repo.id), "latest_only": "false"},
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    ids = [i["id"] for i in response.json()]
    assert str(new_issue.id) in ids
    assert str(issue.id) in ids


def test_list_issues_latest_only_applies_without_repo_id(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    workflow_file: WorkflowFile,
    rule: Rule,
    analysis: WorkflowScan,
    issue: WorkflowFinding,
) -> None:
    """latest_only must filter stale issue rows from an org-wide listing
    (no repo_id), the same as it does when scoped to one repo — otherwise
    a dashboard summing across repos counts issues from every past analysis
    of a workflow file, not just its current one."""
    from datetime import datetime, timezone

    new_analysis = WorkflowScan(
        repo_id=repo.id,
        workflow_file_id=workflow_file.id,
        content_hash=uuid.uuid4().hex,
        status=ScanStatus.completed,
        score=90.0,
        grade="A",
        triggered_by=ScanTrigger.manual,
        branch="main",
        completed_at=datetime.now(timezone.utc),
    )
    db.add(new_analysis)
    db.commit()
    db.refresh(new_analysis)

    new_issue = WorkflowFinding(
        analysis_id=new_analysis.id,
        workflow_file_id=new_analysis.workflow_file_id,
        rule_id=rule.id,
        severity=Severity.high,
        category=Category.security,
        line_start=5,
        line_end=7,
        message="New analysis issue",
        context=None,
    )
    db.add(new_issue)
    db.commit()

    # Act — no repo_id, default latest_only=True (org-wide, e.g. dashboard)
    response = client.get(
        f"{settings.API_V1_STR}/workflow-findings/",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    ids = [i["id"] for i in response.json()]
    assert str(new_issue.id) in ids
    assert str(issue.id) not in ids


# ─── POST /issues/{id}/ignore & /unignore ─────────────────────────────────────


def test_ignore_and_unignore_issue(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    issue: WorkflowFinding,
) -> None:
    # Ignore → status becomes ignored (DB trigger) and ignored_at is set.
    resp = client.post(
        f"{settings.API_V1_STR}/workflow-findings/{issue.id}/ignore",
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"
    db.refresh(issue)
    assert issue.ignored_at is not None
    assert issue.status is FindingStatus.ignored

    # Ignore again is idempotent.
    resp = client.post(
        f"{settings.API_V1_STR}/workflow-findings/{issue.id}/ignore",
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"

    # Unignore → reverts to the underlying (open) state.
    resp = client.post(
        f"{settings.API_V1_STR}/workflow-findings/{issue.id}/unignore",
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
    issue: WorkflowFinding,
) -> None:
    client.post(
        f"{settings.API_V1_STR}/workflow-findings/{issue.id}/ignore",
        headers=superuser_token_headers,
    )
    # Default list excludes ignored issues.
    resp = client.get(
        f"{settings.API_V1_STR}/workflow-findings/",
        params={"repo_id": str(repo.id), "latest_only": "false"},
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200
    assert str(issue.id) not in [i["id"] for i in resp.json()]
    # include_ignored=true surfaces it again.
    resp = client.get(
        f"{settings.API_V1_STR}/workflow-findings/",
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

    def _seed(branch: str, path: str, message: str) -> WorkflowFinding:
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
        analysis = WorkflowScan(
            repo_id=repo.id,
            workflow_file_id=wf.id,
            content_hash=wf.content_hash,
            status=ScanStatus.completed,
            triggered_by=ScanTrigger.manual,
            branch=branch,
        )
        db.add(analysis)
        db.commit()
        db.refresh(analysis)
        issue = WorkflowFinding(
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

    url = f"{settings.API_V1_STR}/workflow-findings/"
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
