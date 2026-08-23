"""Tests for the /api/v1/cloud-accounts/ endpoints."""

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    AnalysisTrigger,
    CloudAccount,
    CloudAccountStatus,
    CloudFinding,
    CloudScan,
    FindingResolutionReason,
    FindingStatus,
    IssueCategory,
    IssueSeverity,
    Organization,
    OrgMember,
    OrgRole,
    Rule,
    RuleDomain,
    ScanStatus,
    User,
    UserTier,
)

# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def org(db: Session) -> Organization:
    organization = Organization(
        name=f"cloudapi-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free
    )
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization


@pytest.fixture()
def cloud_account(db: Session, org: Organization) -> CloudAccount:
    account = CloudAccount(
        org_id=org.id,
        display_name="prod",
        role_arn="arn:aws:iam::123456789012:role/greensecops",
        external_id=uuid.uuid4().hex,
        regions="us-east-1,eu-west-1",
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@pytest.fixture()
def seeded_cloud_rule(db: Session) -> Rule:
    rule = db.exec(select(Rule).where(Rule.domain == RuleDomain.cloud_aws)).first()
    assert rule is not None
    return rule


@pytest.fixture()
def completed_scan(db: Session, cloud_account: CloudAccount) -> CloudScan:
    scan = CloudScan(
        cloud_account_id=cloud_account.id,
        status=ScanStatus.completed,
        triggered_by=AnalysisTrigger.manual,
        resource_count=5,
        score=72.0,
        grade="B",
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)
    return scan


# ─── POST /cloud-accounts/ ──────────────────────────────────────────────────


def test_create_cloud_account(
    client: TestClient, superuser_token_headers: dict[str, str], org: Organization
) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/cloud-accounts/",
        headers=superuser_token_headers,
        json={
            "org_id": str(org.id),
            "display_name": "prod",
            "role_arn": "arn:aws:iam::123456789012:role/greensecops",
            "regions": ["us-east-1"],
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["display_name"] == "prod"
    assert body["org_id"] == str(org.id)
    assert body["status"] == "pending_verification"
    assert body["regions"] == ["us-east-1"]
    # A generated, unguessable external_id — never empty, never client-supplied.
    assert len(body["external_id"]) >= 32


def test_create_cloud_account_generates_unique_external_ids(
    client: TestClient, superuser_token_headers: dict[str, str], org: Organization
) -> None:
    def _create() -> str:
        response = client.post(
            f"{settings.API_V1_STR}/cloud-accounts/",
            headers=superuser_token_headers,
            json={
                "org_id": str(org.id),
                "display_name": "acct",
                "role_arn": "arn:aws:iam::123456789012:role/greensecops",
                "regions": [],
            },
        )
        return str(response.json()["external_id"])

    assert _create() != _create()


# ─── GET /cloud-accounts/ ───────────────────────────────────────────────────


def test_list_cloud_accounts(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    org: Organization,
    cloud_account: CloudAccount,
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/cloud-accounts/",
        headers=superuser_token_headers,
        params={"org_id": str(org.id)},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == str(cloud_account.id)


def test_list_cloud_accounts_includes_latest_grade(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    org: Organization,
    cloud_account: CloudAccount,
    completed_scan: CloudScan,
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/cloud-accounts/",
        headers=superuser_token_headers,
        params={"org_id": str(org.id)},
    )
    body = response.json()
    assert body[0]["latest_score"] == 72.0
    assert body[0]["latest_grade"] == "B"


def test_list_cloud_accounts_without_org_id_scoped_to_user_orgs(
    client: TestClient,
    db: Session,
    normal_user_token_headers: dict[str, str],
) -> None:
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None

    my_org = Organization(
        name=f"cloudapi-mine-{uuid.uuid4().hex[:8]}", tier=UserTier.free
    )
    other_org = Organization(
        name=f"cloudapi-theirs-{uuid.uuid4().hex[:8]}", tier=UserTier.free
    )
    db.add(my_org)
    db.add(other_org)
    db.commit()
    db.refresh(my_org)
    db.refresh(other_org)
    db.add(OrgMember(org_id=my_org.id, user_id=user.id, role=OrgRole.owner))
    db.commit()

    my_account = CloudAccount(
        org_id=my_org.id,
        display_name="mine",
        external_id=uuid.uuid4().hex,
    )
    other_account = CloudAccount(
        org_id=other_org.id,
        display_name="theirs",
        external_id=uuid.uuid4().hex,
    )
    db.add(my_account)
    db.add(other_account)
    db.commit()
    db.refresh(my_account)
    db.refresh(other_account)

    response = client.get(
        f"{settings.API_V1_STR}/cloud-accounts/", headers=normal_user_token_headers
    )

    assert response.status_code == 200
    ids = {a["id"] for a in response.json()}
    assert str(my_account.id) in ids
    assert str(other_account.id) not in ids


# ─── PATCH /cloud-accounts/{id}/toggle ──────────────────────────────────────


def test_disable_cloud_account(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    cloud_account: CloudAccount,
) -> None:
    response = client.patch(
        f"{settings.API_V1_STR}/cloud-accounts/{cloud_account.id}/toggle",
        headers=superuser_token_headers,
        params={"enabled": "false"},
    )
    assert response.status_code == 200
    assert response.json()["enabled"] is False


def test_enable_cloud_account_requires_it_be_disabled_first(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    cloud_account: CloudAccount,
) -> None:
    # A freshly created account is pending_verification, not disabled — the
    # "enable" event is only legal from disabled (re-verify before scans
    # resume), so enabling it directly is illegal.
    response = client.patch(
        f"{settings.API_V1_STR}/cloud-accounts/{cloud_account.id}/toggle",
        headers=superuser_token_headers,
        params={"enabled": "true"},
    )
    assert response.status_code == 409


def test_enable_disabled_cloud_account(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    cloud_account: CloudAccount,
) -> None:
    cloud_account.status = CloudAccountStatus.disabled
    db.add(cloud_account)
    db.commit()

    response = client.patch(
        f"{settings.API_V1_STR}/cloud-accounts/{cloud_account.id}/toggle",
        headers=superuser_token_headers,
        params={"enabled": "true"},
    )
    assert response.status_code == 200
    assert response.json()["enabled"] is True


# ─── DELETE /cloud-accounts/{id} ────────────────────────────────────────────


def test_delete_cloud_account_cascades_scans(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    cloud_account: CloudAccount,
    completed_scan: CloudScan,
) -> None:
    account_id = cloud_account.id
    scan_id = completed_scan.id
    response = client.delete(
        f"{settings.API_V1_STR}/cloud-accounts/{account_id}",
        headers=superuser_token_headers,
    )
    assert response.status_code == 204
    assert (
        db.exec(select(CloudAccount).where(CloudAccount.id == account_id)).first()
        is None
    )
    assert db.exec(select(CloudScan).where(CloudScan.id == scan_id)).first() is None


# ─── POST /cloud-accounts/{id}/scan ─────────────────────────────────────────


def test_trigger_cloud_scan(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    cloud_account: CloudAccount,
) -> None:
    with patch("app.workers.tasks.cloud_scan.run_cloud_scan.delay") as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/cloud-accounts/{cloud_account.id}/scan",
            headers=superuser_token_headers,
        )

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    mock_delay.assert_called_once()
    assert mock_delay.call_args.kwargs["cloud_account_id"] == str(cloud_account.id)


def test_trigger_cloud_scan_disabled_account_rejected(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    cloud_account: CloudAccount,
) -> None:
    cloud_account.status = CloudAccountStatus.disabled
    db.add(cloud_account)
    db.commit()

    response = client.post(
        f"{settings.API_V1_STR}/cloud-accounts/{cloud_account.id}/scan",
        headers=superuser_token_headers,
    )
    assert response.status_code == 403


# ─── GET /cloud-accounts/{id}/scans ─────────────────────────────────────────


def test_list_cloud_scans(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    cloud_account: CloudAccount,
    completed_scan: CloudScan,
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/cloud-accounts/{cloud_account.id}/scans",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == str(completed_scan.id)
    assert body[0]["grade"] == "B"
    assert body[0]["resource_count"] == 5


# ─── GET /cloud-accounts/{id}/findings ──────────────────────────────────────


def test_list_cloud_findings_excludes_resolved_by_default(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    cloud_account: CloudAccount,
    completed_scan: CloudScan,
    seeded_cloud_rule: Rule,
) -> None:
    from datetime import datetime, timezone

    open_finding = CloudFinding(
        scan_id=completed_scan.id,
        cloud_account_id=cloud_account.id,
        rule_id=seeded_cloud_rule.id,
        resource_type="aws_s3_bucket",
        resource_id="my-bucket",
        fingerprint=uuid.uuid4().hex[:16],
        severity=IssueSeverity.high,
        category=IssueCategory.security,
        status=FindingStatus.open,
        message="open finding",
    )
    resolved_finding = CloudFinding(
        scan_id=completed_scan.id,
        cloud_account_id=cloud_account.id,
        rule_id=seeded_cloud_rule.id,
        resource_type="aws_s3_bucket",
        resource_id="other-bucket",
        fingerprint=uuid.uuid4().hex[:16],
        severity=IssueSeverity.high,
        category=IssueCategory.security,
        status=FindingStatus.resolved,
        message="resolved finding",
        resolved_at=datetime.now(timezone.utc),
        resolution_reason=FindingResolutionReason.no_longer_detected,
    )
    db.add(open_finding)
    db.add(resolved_finding)
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/cloud-accounts/{cloud_account.id}/findings",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["message"] == "open finding"
    assert body[0]["rule_slug"] == seeded_cloud_rule.slug


def test_list_cloud_findings_include_resolved(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    cloud_account: CloudAccount,
    completed_scan: CloudScan,
    seeded_cloud_rule: Rule,
) -> None:
    from datetime import datetime, timezone

    resolved_finding = CloudFinding(
        scan_id=completed_scan.id,
        cloud_account_id=cloud_account.id,
        rule_id=seeded_cloud_rule.id,
        resource_type="aws_s3_bucket",
        resource_id="other-bucket",
        fingerprint=uuid.uuid4().hex[:16],
        severity=IssueSeverity.high,
        category=IssueCategory.security,
        status=FindingStatus.resolved,
        message="resolved finding",
        resolved_at=datetime.now(timezone.utc),
        resolution_reason=FindingResolutionReason.no_longer_detected,
    )
    db.add(resolved_finding)
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/cloud-accounts/{cloud_account.id}/findings",
        headers=superuser_token_headers,
        params={"include_resolved": "true"},
    )
    assert response.status_code == 200
    assert len(response.json()) == 1
