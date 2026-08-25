"""Tests for the /api/v1/rules/ endpoints."""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import Category, Rule, Severity

# ─── Helpers ─────────────────────────────────────────────────────────────────


def _first_seeded_rule(db: Session) -> Rule:
    """Return the first seeded rule from init_db."""
    return db.exec(select(Rule)).first()  # type: ignore[return-value]


# ─── GET /rules/ ──────────────────────────────────────────────────────────────


def test_list_all_rules(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/rules/",
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0  # seeded rules exist


def test_list_rules_filter_by_category(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/rules/",
        params={"category": "security"},
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    # Every returned rule must be in the security category
    assert all(r["category"] == "security" for r in data)


def test_list_rules_filter_by_enabled(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/rules/",
        params={"enabled": "true"},
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert all(r["enabled"] is True for r in data)


# ─── GET /rules/{id} ──────────────────────────────────────────────────────────


def test_get_rule_found(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    # Arrange — use a seeded rule
    rule = _first_seeded_rule(db)

    # Act
    response = client.get(
        f"{settings.API_V1_STR}/rules/{rule.id}",
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(rule.id)
    assert body["slug"] == rule.slug


def test_get_rule_not_found(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/rules/{uuid.uuid4()}",
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 404
    assert response.json()["detail"] == "Rule not found"


# ─── PATCH /rules/{id}/toggle ─────────────────────────────────────────────────


def test_toggle_rule_by_superuser(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    # Arrange — create a fresh rule to avoid side-effects on seeded data
    rule = Rule(
        slug=f"test-toggle-rule-{uuid.uuid4().hex[:8]}",
        category=Category.energy,
        severity=Severity.low,
        title="Toggle Test Rule",
        description="Used by toggle test",
        enabled=True,
        severity_weight=1.0,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)

    # Act — disable
    response = client.patch(
        f"{settings.API_V1_STR}/rules/{rule.id}/toggle",
        params={"enabled": "false"},
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(rule.id)
    assert body["enabled"] is False

    db.refresh(rule)
    assert rule.enabled is False


def test_toggle_rule_re_enable(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    # Arrange — create a disabled rule
    rule = Rule(
        slug=f"test-reenable-rule-{uuid.uuid4().hex[:8]}",
        category=Category.energy,
        severity=Severity.low,
        title="Re-enable Test Rule",
        description="Used by re-enable test",
        enabled=False,
        severity_weight=1.0,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)

    # Act — re-enable
    response = client.patch(
        f"{settings.API_V1_STR}/rules/{rule.id}/toggle",
        params={"enabled": "true"},
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True


def test_toggle_rule_not_found(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    # Act
    response = client.patch(
        f"{settings.API_V1_STR}/rules/{uuid.uuid4()}/toggle",
        params={"enabled": "true"},
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 404
    assert response.json()["detail"] == "Rule not found"
