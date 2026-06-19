"""Tests for the /api/v1/organizations/ endpoints."""

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    Organization,
    OrgMember,
    OrgRole,
    User,
    UserTier,
)

ORG_URL = f"{settings.API_V1_STR}/organizations"


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def org(db: Session) -> Organization:
    organization = Organization(
        name=f"org-test-{uuid.uuid4().hex[:8]}", tier=UserTier.free
    )
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization


# ─── GET /organizations/ai-providers ─────────────────────────────────────────


def test_list_ai_providers_returns_available_only(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    import app.api.routes.organizations as org_mod

    org_mod._load_provider_catalog.cache_clear()

    with (
        patch.dict(
            org_mod._KEY_ENV,
            {"openai": "sk-test", "anthropic": None, "gemini": None, "ollama": None},
        ),
    ):
        response = client.get(
            f"{ORG_URL}/ai-providers",
            headers=superuser_token_headers,
        )

    assert response.status_code == 200
    data = response.json()
    provider_ids = [p["id"] for p in data["providers"]]
    assert "openai" in provider_ids
    assert "anthropic" not in provider_ids


def test_list_ai_providers_none_available(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    import app.api.routes.organizations as org_mod

    org_mod._load_provider_catalog.cache_clear()

    with patch.dict(
        org_mod._KEY_ENV,
        {"openai": None, "anthropic": None, "gemini": None, "ollama": None},
    ):
        response = client.get(
            f"{ORG_URL}/ai-providers",
            headers=superuser_token_headers,
        )

    assert response.status_code == 200
    assert response.json()["providers"] == []


# ─── GET /organizations/ ─────────────────────────────────────────────────────


def test_list_my_organizations_empty(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    response = client.get(f"{ORG_URL}/", headers=superuser_token_headers)
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_list_my_organizations_with_membership(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
    org: Organization,
) -> None:
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None

    db.add(OrgMember(org_id=org.id, user_id=user.id, role=OrgRole.owner))
    db.commit()

    response = client.get(f"{ORG_URL}/", headers=normal_user_token_headers)

    assert response.status_code == 200
    data = response.json()
    org_ids = [o["id"] for o in data]
    assert str(org.id) in org_ids


# ─── PATCH /organizations/{org_id}/ai-preferences ────────────────────────────


def test_update_org_ai_preferences_as_member(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
    org: Organization,
) -> None:
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None

    existing = db.exec(
        select(OrgMember).where(
            OrgMember.org_id == org.id, OrgMember.user_id == user.id
        )
    ).first()
    if not existing:
        db.add(OrgMember(org_id=org.id, user_id=user.id, role=OrgRole.owner))
        db.commit()

    response = client.patch(
        f"{ORG_URL}/{org.id}/ai-preferences",
        json={"default_llm_provider": "openai", "default_llm_model": "gpt-4o"},
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["default_llm_provider"] == "openai"
    assert body["default_llm_model"] == "gpt-4o"


def test_update_org_ai_preferences_non_member_forbidden(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    other_org = Organization(
        name=f"forbidden-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free
    )
    db.add(other_org)
    db.commit()
    db.refresh(other_org)

    response = client.patch(
        f"{ORG_URL}/{other_org.id}/ai-preferences",
        json={"default_llm_provider": "openai", "default_llm_model": "gpt-4o"},
        headers=normal_user_token_headers,
    )

    assert response.status_code == 403


def test_update_org_ai_preferences_not_found(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    response = client.patch(
        f"{ORG_URL}/{uuid.uuid4()}/ai-preferences",
        json={"default_llm_provider": "openai", "default_llm_model": "gpt-4o"},
        headers=superuser_token_headers,
    )

    assert response.status_code == 404


def test_update_org_ai_preferences_superuser_any_org(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    other_org = Organization(
        name=f"super-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free
    )
    db.add(other_org)
    db.commit()
    db.refresh(other_org)

    response = client.patch(
        f"{ORG_URL}/{other_org.id}/ai-preferences",
        json={
            "default_llm_provider": "anthropic",
            "default_llm_model": "claude-sonnet",
        },
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    assert response.json()["default_llm_provider"] == "anthropic"
