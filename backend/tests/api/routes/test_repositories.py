"""Tests for the /api/v1/repositories/ endpoints."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    Organization,
    OrgMember,
    OrgRole,
    Repository,
    User,
    UserTier,
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
