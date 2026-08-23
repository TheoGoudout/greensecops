"""Unit tests for the cloud_scan Celery task (extracted impl function)."""

import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import Session, col, select

from app.models import (
    Category,
    CloudAccount,
    CloudAccountStatus,
    CloudFinding,
    CloudScan,
    FindingStatus,
    Organization,
    Rule,
    RuleDomain,
    ScanFailureKind,
    ScanStatus,
    Severity,
    UserTier,
)
from app.services.cloud.aws_collector import CloudCollectionError
from app.services.opa.evaluator import CloudOpaViolation, OpaUnavailableError
from app.workers.tasks.cloud_scan import _run_cloud_scan_impl


@pytest.fixture()
def org(db: Session) -> Organization:
    organization = Organization(
        name=f"cloudtask-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free
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
        regions="us-east-1",
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@pytest.fixture()
def seeded_cloud_rule(db: Session) -> Rule:
    rule = db.exec(select(Rule).where(Rule.domain == RuleDomain.cloud_aws)).first()
    assert rule is not None, "No seeded cloud rules found — init_db may not have run"
    return rule


def _patch_collect(
    resources: dict[str, Any] | None = None, *, side_effect: Any = None
) -> Any:
    kwargs = (
        {"side_effect": side_effect}
        if side_effect
        else {"return_value": resources or {}}
    )
    return patch("app.workers.tasks.cloud_scan.collect_account_resources", **kwargs)


def _patch_evaluate(violations: list[CloudOpaViolation]) -> Any:
    return patch(
        "app.workers.tasks.cloud_scan._evaluate",
        new=AsyncMock(return_value=violations),
    )


def test_cloud_account_not_found_returns_error(db: Session) -> None:
    result = _run_cloud_scan_impl(str(uuid.uuid4()))
    assert result["status"] == "error"
    assert result["detail"] == "cloud_account_not_found"


def test_assume_role_failure_marks_scan_failed_and_account_error(
    db: Session, cloud_account: CloudAccount
) -> None:
    with _patch_collect(side_effect=CloudCollectionError("access denied")):
        result = _run_cloud_scan_impl(str(cloud_account.id))

    assert result["status"] == "failed"
    scan = db.get(CloudScan, uuid.UUID(str(result["scan_id"])))
    assert scan is not None
    assert scan.status == ScanStatus.failed
    assert scan.failure_kind == ScanFailureKind.permanent

    db.refresh(cloud_account)
    assert cloud_account.status == CloudAccountStatus.error


def test_opa_unavailable_marks_scan_failed_transient(
    db: Session, cloud_account: CloudAccount
) -> None:
    with (
        _patch_collect({"s3_buckets": []}),
        patch(
            "app.workers.tasks.cloud_scan._evaluate",
            new=AsyncMock(side_effect=OpaUnavailableError("opa down")),
        ),
    ):
        result = _run_cloud_scan_impl(str(cloud_account.id))

    assert result["status"] == "failed"
    scan = db.get(CloudScan, uuid.UUID(str(result["scan_id"])))
    assert scan is not None
    assert scan.failure_kind == ScanFailureKind.transient


def test_creates_finding_and_computes_score(
    db: Session, cloud_account: CloudAccount, seeded_cloud_rule: Rule
) -> None:
    resources = {"s3_buckets": [{"name": "my-bucket", "encrypted": False}]}
    violation = CloudOpaViolation(
        rule_slug=seeded_cloud_rule.slug,
        severity=seeded_cloud_rule.severity.value,
        category=seeded_cloud_rule.category.value,
        message="something is wrong",
        resource_type="aws_s3_bucket",
        resource_id="my-bucket",
        region="us-east-1",
    )
    with _patch_collect(resources), _patch_evaluate([violation]):
        result = _run_cloud_scan_impl(str(cloud_account.id))

    assert result["status"] == "done"
    assert result["findings"] == 1
    assert isinstance(result["score"], float)
    assert result["score"] < 100.0

    findings = db.exec(
        select(CloudFinding).where(CloudFinding.cloud_account_id == cloud_account.id)
    ).all()
    assert len(findings) == 1
    assert findings[0].resource_id == "my-bucket"
    assert findings[0].region == "us-east-1"
    assert findings[0].status == FindingStatus.open

    db.refresh(cloud_account)
    assert cloud_account.status == CloudAccountStatus.connected
    assert cloud_account.last_synced_at is not None


def test_clean_scan_scores_100_and_grade_a_plus_plus_plus(
    db: Session, cloud_account: CloudAccount
) -> None:
    with _patch_collect({"s3_buckets": []}), _patch_evaluate([]):
        result = _run_cloud_scan_impl(str(cloud_account.id))

    assert result["status"] == "done"
    assert result["findings"] == 0
    assert result["score"] == 100.0
    assert result["grade"] == "A+++"


def test_unknown_rule_slug_is_skipped_not_persisted(
    db: Session, cloud_account: CloudAccount
) -> None:
    violation = CloudOpaViolation(
        rule_slug=f"nonexistent-{uuid.uuid4().hex[:8]}",
        severity=Severity.high.value,
        category=Category.security.value,
        message="orphan violation",
        resource_type="aws_s3_bucket",
        resource_id="my-bucket",
    )
    with _patch_collect({"s3_buckets": []}), _patch_evaluate([violation]):
        result = _run_cloud_scan_impl(str(cloud_account.id))

    assert result["status"] == "done"
    assert result["findings"] == 0


def test_rescan_resolves_stale_findings_not_seen_again(
    db: Session, cloud_account: CloudAccount, seeded_cloud_rule: Rule
) -> None:
    violation = CloudOpaViolation(
        rule_slug=seeded_cloud_rule.slug,
        severity=seeded_cloud_rule.severity.value,
        category=seeded_cloud_rule.category.value,
        message="fixable issue",
        resource_type="aws_s3_bucket",
        resource_id="my-bucket",
    )
    with _patch_collect({"s3_buckets": []}), _patch_evaluate([violation]):
        _run_cloud_scan_impl(str(cloud_account.id))

    # Second scan: the violation is gone (bucket fixed/deleted).
    with _patch_collect({"s3_buckets": []}), _patch_evaluate([]):
        _run_cloud_scan_impl(str(cloud_account.id))

    findings = db.exec(
        select(CloudFinding)
        .where(CloudFinding.cloud_account_id == cloud_account.id)
        .where(col(CloudFinding.resolved_at).is_not(None))
    ).all()
    assert len(findings) == 1
    assert findings[0].status == FindingStatus.resolved


def test_resource_count_reflects_total_collected_resources(
    db: Session, cloud_account: CloudAccount
) -> None:
    resources = {
        "s3_buckets": [{"name": "b1", "encrypted": True}],
        "security_groups": [{"id": "sg-1", "ingress_rules": []}],
        "iam_users": [],
    }
    with _patch_collect(resources), _patch_evaluate([]):
        result = _run_cloud_scan_impl(str(cloud_account.id))

    scan = db.get(CloudScan, uuid.UUID(str(result["scan_id"])))
    assert scan is not None
    assert scan.resource_count == 2
