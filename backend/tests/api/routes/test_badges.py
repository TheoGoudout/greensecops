"""Tests for the /api/v1/badges/ endpoints."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models import (
    Analysis,
    AnalysisStatus,
    Organization,
    Repository,
    ScanTrigger,
    UserTier,
    WorkflowFile,
)

# ─── helpers ──────────────────────────────────────────────────────────────────


def _add_workflow_analysis(
    db: Session,
    repo: Repository,
    path: str,
    score: float,
    grade: str,
    branch: str = "main",
) -> None:
    wf = WorkflowFile(
        repo_id=repo.id,
        path=path,
        content_hash=uuid.uuid4().hex,
        raw_content="on: push\njobs: {}",
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    db.add(
        Analysis(
            repo_id=repo.id,
            workflow_file_id=wf.id,
            content_hash=wf.content_hash,
            status=AnalysisStatus.completed,
            score=score,
            grade=grade,
            triggered_by=ScanTrigger.manual,
            branch=branch,
        )
    )
    db.commit()


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def org(db: Session) -> Organization:
    organization = Organization(
        name=f"badges-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free
    )
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization


@pytest.fixture()
def repo(db: Session, org: Organization) -> Repository:
    # Use a deterministic full_name to make URL construction predictable
    suffix = uuid.uuid4().hex[:8]
    repository = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"badgesowner-{suffix}/repo-{suffix}",
        installation_id=11112,
        default_branch="main",
    )
    db.add(repository)
    db.commit()
    db.refresh(repository)
    return repository


@pytest.fixture()
def private_repo(db: Session, org: Organization) -> Repository:
    suffix = uuid.uuid4().hex[:8]
    repository = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"privowner-{suffix}/repo-{suffix}",
        installation_id=11113,
        default_branch="main",
        is_private=True,
    )
    db.add(repository)
    db.commit()
    db.refresh(repository)
    return repository


@pytest.fixture()
def workflow_file(db: Session, repo: Repository) -> WorkflowFile:
    wf = WorkflowFile(
        repo_id=repo.id,
        path=".github/workflows/badge-test.yml",
        content_hash=uuid.uuid4().hex,
        raw_content="on: push\njobs: {}",
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


@pytest.fixture()
def completed_analysis(
    db: Session, repo: Repository, workflow_file: WorkflowFile
) -> Analysis:
    a = Analysis(
        repo_id=repo.id,
        workflow_file_id=workflow_file.id,
        content_hash=workflow_file.content_hash,
        status=AnalysisStatus.completed,
        score=92.0,
        grade="A+",
        triggered_by=ScanTrigger.manual,
        branch="main",
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


# ─── SVG badge ────────────────────────────────────────────────────────────────


def test_svg_badge_unknown_repo_returns_unknown(
    client: TestClient,
) -> None:
    # Act — owner and repo that don't exist
    response = client.get(
        f"{settings.API_V1_STR}/badges/ghost-owner/ghost-repo/main.svg"
    )

    # Assert
    assert response.status_code == 200
    assert "image/svg+xml" in response.headers.get("content-type", "")
    assert b"?" in response.content


def test_svg_badge_known_repo_no_analysis(
    client: TestClient,
    repo: Repository,
) -> None:
    # Arrange — repo exists but no completed analysis for this branch
    owner, repo_name = repo.full_name.split("/", 1)

    # Act
    response = client.get(
        f"{settings.API_V1_STR}/badges/{owner}/{repo_name}/nonexistent-branch.svg"
    )

    # Assert
    assert response.status_code == 200
    assert "image/svg+xml" in response.headers.get("content-type", "")
    # No grade → unknown badge with "?"
    assert b"?" in response.content


def test_svg_badge_known_repo_with_grade(
    client: TestClient,
    repo: Repository,
    completed_analysis: Analysis,
) -> None:
    # Arrange
    owner, repo_name = repo.full_name.split("/", 1)

    # Act
    response = client.get(f"{settings.API_V1_STR}/badges/{owner}/{repo_name}/main.svg")

    # Assert
    assert response.status_code == 200
    assert "image/svg+xml" in response.headers.get("content-type", "")
    assert b"A+" in response.content


# ─── JSON badge ───────────────────────────────────────────────────────────────


def test_json_badge_unknown_repo(
    client: TestClient,
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/badges/ghost-owner/ghost-repo/main.json"
    )

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["schemaVersion"] == 1
    assert body["message"] == "not configured"


def test_json_badge_pending(
    client: TestClient,
    repo: Repository,
) -> None:
    # Arrange — repo exists but no completed analysis on this branch
    owner, repo_name = repo.full_name.split("/", 1)

    # Act
    response = client.get(
        f"{settings.API_V1_STR}/badges/{owner}/{repo_name}/pending-branch.json"
    )

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["schemaVersion"] == 1
    assert body["message"] == "pending"


def test_json_badge_with_grade(
    client: TestClient,
    repo: Repository,
    completed_analysis: Analysis,
) -> None:
    # Arrange
    owner, repo_name = repo.full_name.split("/", 1)

    # Act
    response = client.get(f"{settings.API_V1_STR}/badges/{owner}/{repo_name}/main.json")

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["schemaVersion"] == 1
    assert body["message"] == "A+"
    assert "color" in body
    assert body.get("cacheSeconds") == 300


# ─── Private-repo signature enforcement ───────────────────────────────────────


def _add_grade(db: Session, repo: Repository) -> None:
    _add_workflow_analysis(db, repo, ".github/workflows/ci.yml", score=92.0, grade="A+")


def test_private_svg_without_sig_returns_unknown(
    client: TestClient, db: Session, private_repo: Repository
) -> None:
    _add_grade(db, private_repo)
    owner, name = private_repo.full_name.split("/", 1)

    response = client.get(f"{settings.API_V1_STR}/badges/{owner}/{name}/main.svg")

    assert response.status_code == 200
    # Grade is hidden without a valid signature.
    assert b"A+" not in response.content
    assert b"?" in response.content


def test_private_svg_with_valid_sig_returns_grade(
    client: TestClient, db: Session, private_repo: Repository
) -> None:
    from app.services.badge_signing import repo_badge_message, sign_badge

    _add_grade(db, private_repo)
    owner, name = private_repo.full_name.split("/", 1)
    sig = sign_badge(repo_badge_message(owner, name, "main"))

    response = client.get(
        f"{settings.API_V1_STR}/badges/{owner}/{name}/main.svg", params={"sig": sig}
    )

    assert response.status_code == 200
    assert b"A+" in response.content


def test_private_svg_with_wrong_sig_returns_unknown(
    client: TestClient, db: Session, private_repo: Repository
) -> None:
    _add_grade(db, private_repo)
    owner, name = private_repo.full_name.split("/", 1)

    response = client.get(
        f"{settings.API_V1_STR}/badges/{owner}/{name}/main.svg",
        params={"sig": "deadbeef"},
    )

    assert response.status_code == 200
    assert b"A+" not in response.content


def test_private_json_without_sig_not_configured(
    client: TestClient, db: Session, private_repo: Repository
) -> None:
    _add_grade(db, private_repo)
    owner, name = private_repo.full_name.split("/", 1)

    response = client.get(f"{settings.API_V1_STR}/badges/{owner}/{name}/main.json")

    assert response.status_code == 200
    assert response.json()["message"] == "not configured"


def test_private_json_with_valid_sig_returns_grade(
    client: TestClient, db: Session, private_repo: Repository
) -> None:
    from app.services.badge_signing import repo_badge_message, sign_badge

    _add_grade(db, private_repo)
    owner, name = private_repo.full_name.split("/", 1)
    sig = sign_badge(repo_badge_message(owner, name, "main"))

    response = client.get(
        f"{settings.API_V1_STR}/badges/{owner}/{name}/main.json", params={"sig": sig}
    )

    assert response.status_code == 200
    assert response.json()["message"] == "A+"


# ─── Multi-workflow average grade ─────────────────────────────────────────────


def test_svg_badge_avg_grade_across_workflow_files(
    client: TestClient,
    db: Session,
    repo: Repository,
) -> None:
    # Arrange — workflow files with scores 80 and 60 → avg 70 → grade B
    # A naive "most-recent analysis" approach would show whichever ran last;
    # the correct behaviour averages latest analysis per workflow file.
    _add_workflow_analysis(db, repo, ".github/workflows/ci.yml", score=80.0, grade="B")
    _add_workflow_analysis(
        db, repo, ".github/workflows/deploy.yml", score=60.0, grade="C"
    )
    owner, repo_name = repo.full_name.split("/", 1)

    response = client.get(f"{settings.API_V1_STR}/badges/{owner}/{repo_name}/main.svg")

    assert response.status_code == 200
    assert b"B" in response.content


def test_json_badge_avg_grade_across_workflow_files(
    client: TestClient,
    db: Session,
    repo: Repository,
) -> None:
    # Arrange — same scenario as SVG test above
    _add_workflow_analysis(db, repo, ".github/workflows/ci.yml", score=80.0, grade="B")
    _add_workflow_analysis(
        db, repo, ".github/workflows/deploy.yml", score=60.0, grade="C"
    )
    owner, repo_name = repo.full_name.split("/", 1)

    response = client.get(f"{settings.API_V1_STR}/badges/{owner}/{repo_name}/main.json")

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "B"
    assert body.get("cacheSeconds") == 300
