"""Tests for the /api/v1/repositories/ endpoints."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    Analysis,
    AnalysisStatus,
    AnalysisTrigger,
    Organization,
    OrgMember,
    OrgRole,
    Repository,
    User,
    UserTier,
    WorkflowFile,
)

# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def org(db: Session) -> Organization:
    organization = Organization(
        name=f"repos-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free
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
        full_name=f"repoowner/repo-{uuid.uuid4().hex[:8]}",
        installation_id=11111,
        enabled=True,
    )
    db.add(repository)
    db.commit()
    db.refresh(repository)
    return repository


# ─── GET /repositories/ ──────────────────────────────────────────────────────


def test_list_repositories_empty(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    # Arrange — create a fresh org with no repos
    fresh_org = Organization(
        name=f"empty-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free
    )
    db.add(fresh_org)
    db.commit()
    db.refresh(fresh_org)

    # Act
    response = client.get(
        f"{settings.API_V1_STR}/repositories/",
        params={"org_id": str(fresh_org.id)},
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 0


def test_list_repositories_with_data(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
    org: Organization,
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/repositories/",
        params={"org_id": str(org.id)},
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    ids = [r["id"] for r in data]
    assert str(repo.id) in ids


def test_list_repositories_filter_by_enabled(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    org: Organization,
) -> None:
    # Arrange — create one enabled and one disabled repo
    enabled_repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"owner/enabled-{uuid.uuid4().hex[:8]}",
        installation_id=22222,
        enabled=True,
    )
    disabled_repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"owner/disabled-{uuid.uuid4().hex[:8]}",
        installation_id=33333,
        enabled=False,
    )
    db.add(enabled_repo)
    db.add(disabled_repo)
    db.commit()
    db.refresh(enabled_repo)
    db.refresh(disabled_repo)

    # Act — only enabled
    response = client.get(
        f"{settings.API_V1_STR}/repositories/",
        params={"org_id": str(org.id), "enabled": "true"},
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    returned_ids = {r["id"] for r in data}
    assert str(enabled_repo.id) in returned_ids
    assert str(disabled_repo.id) not in returned_ids


# ─── GET /repositories/{id} ───────────────────────────────────────────────────


def test_get_repository_found(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/repositories/{repo.id}",
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(repo.id)
    assert body["full_name"] == repo.full_name


def test_get_repository_not_found(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/repositories/{uuid.uuid4()}",
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 404
    assert response.json()["detail"] == "Repository not found"


# ─── PATCH /repositories/{id}/toggle ─────────────────────────────────────────


def test_toggle_repository_enable(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    org: Organization,
) -> None:
    # Arrange — create a disabled repo
    repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"owner/toggle-{uuid.uuid4().hex[:8]}",
        installation_id=44444,
        enabled=False,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    # Act
    response = client.patch(
        f"{settings.API_V1_STR}/repositories/{repo.id}/toggle",
        params={"enabled": "true"},
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["repo_id"] == str(repo.id)

    db.refresh(repo)
    assert repo.enabled is True


def test_toggle_repository_disable(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
    db: Session,
) -> None:
    # Act
    response = client.patch(
        f"{settings.API_V1_STR}/repositories/{repo.id}/toggle",
        params={"enabled": "false"},
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False

    db.refresh(repo)
    assert repo.enabled is False


def test_toggle_repository_not_found(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    # Act
    response = client.patch(
        f"{settings.API_V1_STR}/repositories/{uuid.uuid4()}/toggle",
        params={"enabled": "true"},
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 404
    assert response.json()["detail"] == "Repository not found"


# ─── Org-scoped access for non-superusers ────────────────────────────────────


def _make_org_with_repo(db: Session, suffix: str) -> tuple[Organization, Repository]:
    organization = Organization(name=f"scope-{suffix}-{uuid.uuid4().hex[:6]}")
    db.add(organization)
    db.commit()
    db.refresh(organization)
    repository = Repository(
        org_id=organization.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"owner/scope-{suffix}-{uuid.uuid4().hex[:6]}",
        installation_id=int(uuid.uuid4().int % 10**6),
        enabled=True,
    )
    db.add(repository)
    db.commit()
    db.refresh(repository)
    return organization, repository


def test_list_repositories_scoped_to_user_orgs(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None

    my_org, my_repo = _make_org_with_repo(db, "mine")
    _other_org, other_repo = _make_org_with_repo(db, "theirs")
    db.add(OrgMember(org_id=my_org.id, user_id=user.id, role=OrgRole.owner))
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/repositories/", headers=normal_user_token_headers
    )

    assert response.status_code == 200
    ids = {r["id"] for r in response.json()}
    assert str(my_repo.id) in ids
    assert str(other_repo.id) not in ids


def test_get_repository_cross_org_returns_404(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    _other_org, other_repo = _make_org_with_repo(db, "getforbidden")

    response = client.get(
        f"{settings.API_V1_STR}/repositories/{other_repo.id}",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Repository not found"


def test_toggle_repository_cross_org_returns_404(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    _other_org, other_repo = _make_org_with_repo(db, "toggleforbidden")

    response = client.patch(
        f"{settings.API_V1_STR}/repositories/{other_repo.id}/toggle",
        params={"enabled": "false"},
        headers=normal_user_token_headers,
    )

    assert response.status_code == 404
    db.refresh(other_repo)
    assert other_repo.enabled is True


# ─── Grade fields on list / get endpoints ─────────────────────────────────────


def _make_workflow_file(
    db: Session, repo: Repository, path: str = ".github/workflows/ci.yml"
) -> WorkflowFile:
    wf = WorkflowFile(
        repo_id=repo.id,
        path=path,
        content_hash=uuid.uuid4().hex,
        raw_content="on: push\njobs: {}",
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


def _make_completed_analysis(
    db: Session, repo: Repository, wf: WorkflowFile, score: float, grade: str
) -> Analysis:
    a = Analysis(
        repo_id=repo.id,
        workflow_file_id=wf.id,
        content_hash=wf.content_hash,
        status=AnalysisStatus.completed,
        score=score,
        grade=grade,
        triggered_by=AnalysisTrigger.manual,
        branch="main",
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def test_list_repositories_grade_null_without_analyses(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
    org: Organization,
) -> None:
    # Arrange — repo exists but has no completed analyses
    response = client.get(
        f"{settings.API_V1_STR}/repositories/",
        params={"org_id": str(org.id)},
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    data = response.json()
    repo_data = next(r for r in data if r["id"] == str(repo.id))
    assert repo_data["avg_score"] is None
    assert repo_data["grade"] == "-"


def test_list_repositories_grade_populated(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    org: Organization,
) -> None:
    # Arrange — two workflow files with scores 80 and 60 → avg 70 → grade B
    wf1 = _make_workflow_file(db, repo, ".github/workflows/ci.yml")
    wf2 = _make_workflow_file(db, repo, ".github/workflows/deploy.yml")
    _make_completed_analysis(db, repo, wf1, score=80.0, grade="B")
    _make_completed_analysis(db, repo, wf2, score=60.0, grade="C")

    response = client.get(
        f"{settings.API_V1_STR}/repositories/",
        params={"org_id": str(org.id)},
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    data = response.json()
    repo_data = next(r for r in data if r["id"] == str(repo.id))
    assert repo_data["avg_score"] == 70.0
    assert repo_data["grade"] == "B"


def test_get_repository_grade_populated(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
) -> None:
    # Arrange — one workflow file with score 92 → grade A+
    wf = _make_workflow_file(db, repo)
    _make_completed_analysis(db, repo, wf, score=92.0, grade="A+")

    response = client.get(
        f"{settings.API_V1_STR}/repositories/{repo.id}",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["avg_score"] == 92.0
    assert body["grade"] == "A+"


# ─── GET /repositories/external ─────────────────────────────────────────────


def test_list_external_repositories_empty(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/repositories/external",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_list_external_repositories_returns_external_only(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    org: Organization,
) -> None:
    ext_repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"ext-owner/ext-{uuid.uuid4().hex[:8]}",
        installation_id=None,
        enabled=True,
        is_external=True,
    )
    normal_repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"normal-owner/normal-{uuid.uuid4().hex[:8]}",
        installation_id=55555,
        enabled=True,
        is_external=False,
    )
    db.add(ext_repo)
    db.add(normal_repo)
    db.commit()
    db.refresh(ext_repo)
    db.refresh(normal_repo)

    response = client.get(
        f"{settings.API_V1_STR}/repositories/external",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    ids = {r["id"] for r in response.json()}
    assert str(ext_repo.id) in ids
    assert str(normal_repo.id) not in ids


# ─── GET /repositories/{id}/workflow-files ───────────────────────────────────


def test_list_workflow_files_empty(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
) -> None:
    # Arrange — repo has no workflow files
    response = client.get(
        f"{settings.API_V1_STR}/repositories/{repo.id}/workflow-files",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    assert response.json() == []


def test_list_workflow_files_returns_files(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
) -> None:
    # Arrange — add a workflow file to the repo
    wf = WorkflowFile(
        repo_id=repo.id,
        path=".github/workflows/ci.yml",
        content_hash=uuid.uuid4().hex,
        raw_content="on: push\njobs: {}",
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)

    response = client.get(
        f"{settings.API_V1_STR}/repositories/{repo.id}/workflow-files",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    paths = [f["path"] for f in data]
    assert ".github/workflows/ci.yml" in paths


def test_list_workflow_files_not_found(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/repositories/{uuid.uuid4()}/workflow-files",
        headers=superuser_token_headers,
    )

    assert response.status_code == 404


# ─── POST /repositories/{id}/integrate-action ───────────────────────────────


def test_integrate_action_no_workflow_files(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/repositories/{repo.id}/integrate-action",
        headers=superuser_token_headers,
    )
    assert response.status_code == 404
    assert "No workflow files" in response.json()["detail"]


def test_integrate_action_no_installation(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    org: Organization,
) -> None:
    repo_no_install = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"owner/no-install-{uuid.uuid4().hex[:8]}",
        installation_id=None,
        enabled=True,
    )
    db.add(repo_no_install)
    db.commit()
    db.refresh(repo_no_install)
    wf = WorkflowFile(
        repo_id=repo_no_install.id,
        path=".github/workflows/ci.yml",
        content_hash=uuid.uuid4().hex,
        raw_content="on: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n",
    )
    db.add(wf)
    db.commit()

    response = client.post(
        f"{settings.API_V1_STR}/repositories/{repo_no_install.id}/integrate-action",
        headers=superuser_token_headers,
    )
    assert response.status_code == 400
    assert "no GitHub App installation" in response.json()["detail"]


def test_integrate_action_already_present(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    org: Organization,
) -> None:
    from unittest.mock import AsyncMock

    repo_with_install = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"owner/already-int-{uuid.uuid4().hex[:8]}",
        installation_id=99999,
        enabled=True,
    )
    db.add(repo_with_install)
    db.commit()
    db.refresh(repo_with_install)
    wf = WorkflowFile(
        repo_id=repo_with_install.id,
        path=".github/workflows/ci.yml",
        content_hash=uuid.uuid4().hex,
        raw_content=(
            "on: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n"
            "    permissions:\n      id-token: write\n    steps:\n"
            f"      - uses: {settings.GITHUB_ACTION_REF}\n"
        ),
    )
    db.add(wf)
    db.commit()

    mock_client = AsyncMock()
    mock_client.get_installation_token = AsyncMock(return_value="tok")

    from unittest.mock import MagicMock, patch

    from github.GithubException import GithubException

    from app.api.deps import get_github_app_client
    from app.main import app as fastapi_app

    # Live-content and README fetches 404, so the route falls back to the
    # stored raw_content (already integrated) and skips badge injection.
    gh_repo = MagicMock()
    gh_repo.get_contents.side_effect = GithubException(404, "Not Found", None)
    gh_repo.get_readme.side_effect = GithubException(404, "Not Found", None)
    gh_instance = MagicMock()
    gh_instance.get_repo.return_value = gh_repo

    fastapi_app.dependency_overrides[get_github_app_client] = lambda: mock_client
    try:
        with patch("github.Github", return_value=gh_instance):
            response = client.post(
                f"{settings.API_V1_STR}/repositories/{repo_with_install.id}/integrate-action",
                headers=superuser_token_headers,
            )
    finally:
        fastapi_app.dependency_overrides.clear()

    assert response.status_code == 409
    assert "already present" in response.json()["detail"]


# ─── auto-fix toggle and branches listing ────────────────────────────────────


def test_toggle_auto_fix_enable(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
    db: Session,
) -> None:
    response = client.patch(
        f"{settings.API_V1_STR}/repositories/{repo.id}/auto-fix",
        params={"enabled": "true"},
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["auto_fix_enabled"] is True
    assert body["repo_id"] == str(repo.id)

    db.refresh(repo)
    assert repo.auto_fix_enabled is True


def test_toggle_auto_fix_not_found(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    response = client.patch(
        f"{settings.API_V1_STR}/repositories/{uuid.uuid4()}/auto-fix",
        params={"enabled": "true"},
        headers=superuser_token_headers,
    )

    assert response.status_code == 404


def test_list_repository_branches(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
    db: Session,
) -> None:
    from app.models import Analysis, AnalysisStatus, WorkflowFile

    wf = WorkflowFile(
        repo_id=repo.id,
        path=".github/workflows/branches.yml",
        content_hash=uuid.uuid4().hex,
        raw_content="on: push\n",
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    for branch, status in [
        ("main", AnalysisStatus.completed),
        ("dev", AnalysisStatus.completed),
        ("main", AnalysisStatus.completed),
        ("wip", AnalysisStatus.pending),
    ]:
        db.add(
            Analysis(
                repo_id=repo.id,
                workflow_file_id=wf.id,
                content_hash=uuid.uuid4().hex,
                status=status,
                branch=branch,
            )
        )
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/repositories/{repo.id}/branches",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    assert response.json() == ["dev", "main"]
