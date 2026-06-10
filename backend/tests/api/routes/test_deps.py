"""Tests for auth dependency edge cases."""

import uuid
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.core.security import create_access_token
from app.crud import create_user
from app.models import UserCreate


def test_invalid_token_returns_403(client: TestClient) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/users/me",
        headers={"Authorization": "Bearer this-is-not-a-valid-token"},
    )
    assert response.status_code == 403


def test_inactive_user_returns_400(client: TestClient, db: Session) -> None:
    user_in = UserCreate(
        email=f"inactive-{uuid.uuid4().hex[:8]}@example.com",
        password="testpassword123",
    )
    user = create_user(session=db, user_create=user_in)
    user.is_active = False
    db.add(user)
    db.commit()

    token = create_access_token(
        subject=str(user.id), expires_delta=timedelta(minutes=30)
    )
    response = client.get(
        f"{settings.API_V1_STR}/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400


def test_token_for_nonexistent_user_returns_404(client: TestClient) -> None:
    token = create_access_token(
        subject=str(uuid.uuid4()), expires_delta=timedelta(minutes=30)
    )
    response = client.get(
        f"{settings.API_V1_STR}/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404
