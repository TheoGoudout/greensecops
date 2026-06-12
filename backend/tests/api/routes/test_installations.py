"""Tests for the /api/v1/installations/ endpoints."""

import uuid
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import Organization, OrgMember, OrgRole, User
from app.services.github.app_client import UserInstallation

SYNC_URL = f"{settings.API_V1_STR}/installations/sync"


def _override_github_client(installations: list[UserInstallation]) -> AsyncMock:
    mock_client = AsyncMock()
    mock_client.exchange_oauth_code.return_value = "gho_user_token"
    mock_client.list_user_installations.return_value = installations
    return mock_client


def test_sync_requires_auth(client: TestClient) -> None:
    response = client.post(SYNC_URL, json={"code": "abc"})
    assert response.status_code == 401


def test_sync_links_all_installations(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    # Arrange — two installations (personal + org) returned by GitHub.
    acc1 = int(uuid.uuid4().int % 10**9)
    acc2 = int(uuid.uuid4().int % 10**9)
    inst1 = int(uuid.uuid4().int % 10**6) + 800000
    inst2 = int(uuid.uuid4().int % 10**6) + 810000
    installations = [
        UserInstallation(inst1, acc1, f"alice-{acc1}", "User"),
        UserInstallation(inst2, acc2, f"acme-{acc2}", "Organization"),
    ]
    mock_client = _override_github_client(installations)

    from app.api.deps import get_github_app_client
    from app.main import app

    app.dependency_overrides[get_github_app_client] = lambda: mock_client
    try:
        with patch(
            "app.api.routes.installations._enqueue_installation_sync"
        ) as enqueue:
            response = client.post(
                SYNC_URL, json={"code": "valid"}, headers=normal_user_token_headers
            )
    finally:
        app.dependency_overrides.clear()

    # Assert — both orgs returned + persisted.
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2

    org1 = db.exec(
        select(Organization).where(Organization.installation_id == inst1)
    ).first()
    org2 = db.exec(
        select(Organization).where(Organization.installation_id == inst2)
    ).first()
    assert org1 is not None and org2 is not None
    assert org1.github_org_id == acc1

    # Owner membership for the caller on both orgs.
    user = db.exec(
        select(User).where(User.email == settings.EMAIL_TEST_USER)
    ).first()
    assert user is not None
    for org in (org1, org2):
        member = db.get(OrgMember, (org.id, user.id))
        assert member is not None
        assert member.role == OrgRole.owner

    # Sync enqueued for each installation.
    assert enqueue.call_count == 2
    enqueued_ids = {c.args[0] for c in enqueue.call_args_list}
    assert enqueued_ids == {inst1, inst2}


def test_sync_is_idempotent(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    acc = int(uuid.uuid4().int % 10**9)
    inst = int(uuid.uuid4().int % 10**6) + 820000
    installations = [UserInstallation(inst, acc, f"idem-{acc}", "User")]
    mock_client = _override_github_client(installations)

    from app.api.deps import get_github_app_client
    from app.main import app

    app.dependency_overrides[get_github_app_client] = lambda: mock_client
    try:
        with patch("app.api.routes.installations._enqueue_installation_sync"):
            r1 = client.post(
                SYNC_URL, json={"code": "v1"}, headers=normal_user_token_headers
            )
            r2 = client.post(
                SYNC_URL, json={"code": "v2"}, headers=normal_user_token_headers
            )
    finally:
        app.dependency_overrides.clear()

    assert r1.status_code == 200 and r2.status_code == 200
    orgs = db.exec(
        select(Organization).where(Organization.installation_id == inst)
    ).all()
    assert len(orgs) == 1


def test_sync_oauth_failure_returns_400(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    mock_client = AsyncMock()
    mock_client.exchange_oauth_code.side_effect = Exception("bad_verification_code")

    from app.api.deps import get_github_app_client
    from app.main import app

    app.dependency_overrides[get_github_app_client] = lambda: mock_client
    try:
        response = client.post(
            SYNC_URL, json={"code": "bad"}, headers=normal_user_token_headers
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert "GitHub installation sync failed" in response.json()["detail"]
