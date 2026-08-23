"""Round-trip tests for the Terraform/cloud posture schema foundations."""

import uuid

import pytest
from sqlmodel import Session, select

from app.models import (
    CloudAccount,
    CloudAccountStatus,
    CloudFinding,
    CloudProvider,
    CloudScan,
    FindingStatus,
    IssueCategory,
    IssueSeverity,
    Organization,
    Repository,
    Rule,
    RuleDomain,
    ScanStatus,
    TerraformFinding,
    TerraformRoot,
    TerraformScan,
    UserTier,
)


@pytest.fixture()
def org(db: Session) -> Organization:
    organization = Organization(
        name=f"iac-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free
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
        full_name=f"acme/iac-repo-{uuid.uuid4().hex[:8]}",
        enabled=True,
    )
    db.add(repository)
    db.commit()
    db.refresh(repository)
    return repository


@pytest.fixture()
def terraform_rule(db: Session) -> Rule:
    rule = Rule(
        slug=f"tf_public_s3_bucket_{uuid.uuid4().hex[:8]}",
        domain=RuleDomain.iac_terraform,
        category=IssueCategory.security,
        severity=IssueSeverity.high,
        title="Public S3 bucket",
        description="An aws_s3_bucket resource has no access-block configured.",
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@pytest.fixture()
def cloud_rule(db: Session) -> Rule:
    rule = Rule(
        slug=f"cloud_open_ingress_{uuid.uuid4().hex[:8]}",
        domain=RuleDomain.cloud_aws,
        category=IssueCategory.security,
        severity=IssueSeverity.critical,
        title="Security group open to the world",
        description="A security group allows ingress from 0.0.0.0/0.",
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def test_rule_domain_defaults_to_workflow(db: Session) -> None:
    rule = Rule(
        slug=f"workflow_rule_{uuid.uuid4().hex[:8]}",
        category=IssueCategory.reliability,
        severity=IssueSeverity.medium,
        title="Some workflow rule",
        description="Existing-style rule created without an explicit domain.",
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)

    assert rule.domain == RuleDomain.ci_workflow


def test_terraform_root_scan_finding_round_trip(
    db: Session, repo: Repository, terraform_rule: Rule
) -> None:
    root = TerraformRoot(repo_id=repo.id, root_path="infra/prod")
    db.add(root)
    db.commit()
    db.refresh(root)

    scan = TerraformScan(
        terraform_root_id=root.id,
        status=ScanStatus.completed,
        score=82.5,
        grade="B",
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)

    finding = TerraformFinding(
        scan_id=scan.id,
        terraform_root_id=root.id,
        rule_id=terraform_rule.id,
        resource_address="aws_s3_bucket.data",
        file_path="infra/prod/storage.tf",
        line_start=12,
        line_end=12,
        fingerprint=uuid.uuid4().hex[:16],
        severity=IssueSeverity.high,
        category=IssueCategory.security,
        message="Bucket has no access-block configured.",
    )
    db.add(finding)
    db.commit()
    db.refresh(finding)

    db.refresh(root)
    db.refresh(scan)
    assert root.scans[0].id == scan.id
    assert scan.findings[0].id == finding.id
    assert finding.status == FindingStatus.open
    assert scan.terraform_root.id == root.id

    # Cascade: deleting the root removes its scans and their findings.
    root_id = root.id
    db.delete(root)
    db.commit()
    assert db.get(TerraformScan, scan.id) is None
    assert db.get(TerraformFinding, finding.id) is None
    assert (
        db.exec(select(TerraformRoot).where(TerraformRoot.id == root_id)).first()
        is None
    )


def test_terraform_finding_fingerprint_unique_per_root(
    db: Session, repo: Repository, terraform_rule: Rule
) -> None:
    root = TerraformRoot(repo_id=repo.id, root_path=f"infra/{uuid.uuid4().hex[:8]}")
    db.add(root)
    db.commit()
    db.refresh(root)

    scan = TerraformScan(terraform_root_id=root.id, status=ScanStatus.completed)
    db.add(scan)
    db.commit()
    db.refresh(scan)

    fingerprint = uuid.uuid4().hex[:16]
    db.add(
        TerraformFinding(
            scan_id=scan.id,
            terraform_root_id=root.id,
            rule_id=terraform_rule.id,
            file_path="main.tf",
            fingerprint=fingerprint,
            severity=IssueSeverity.medium,
            category=IssueCategory.security,
            message="first",
        )
    )
    db.commit()

    db.add(
        TerraformFinding(
            scan_id=scan.id,
            terraform_root_id=root.id,
            rule_id=terraform_rule.id,
            file_path="main.tf",
            fingerprint=fingerprint,
            severity=IssueSeverity.medium,
            category=IssueCategory.security,
            message="duplicate fingerprint on the same root",
        )
    )
    with pytest.raises(Exception):  # noqa: B017 — IntegrityError from the unique constraint
        db.commit()
    db.rollback()


def test_cloud_account_scan_finding_round_trip(
    db: Session, org: Organization, cloud_rule: Rule
) -> None:
    account = CloudAccount(
        org_id=org.id,
        provider=CloudProvider.aws,
        display_name="Production AWS",
        role_arn="arn:aws:iam::123456789012:role/greensecops-readonly",
        external_id=uuid.uuid4().hex,
        regions="us-east-1,eu-west-1",
        status=CloudAccountStatus.connected,
    )
    db.add(account)
    db.commit()
    db.refresh(account)

    scan = CloudScan(
        cloud_account_id=account.id,
        status=ScanStatus.completed,
        region="us-east-1",
        resource_count=42,
        score=91.0,
        grade="A",
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)

    finding = CloudFinding(
        scan_id=scan.id,
        cloud_account_id=account.id,
        rule_id=cloud_rule.id,
        resource_type="AWS::EC2::SecurityGroup",
        resource_id="sg-0123456789abcdef0",
        region="us-east-1",
        fingerprint=uuid.uuid4().hex[:16],
        severity=IssueSeverity.critical,
        category=IssueCategory.security,
        message="Ingress rule allows 0.0.0.0/0 on port 22.",
    )
    db.add(finding)
    db.commit()
    db.refresh(finding)

    db.refresh(account)
    db.refresh(scan)
    assert account.scans[0].id == scan.id
    assert scan.findings[0].id == finding.id
    assert finding.status == FindingStatus.open

    # Cascade: deleting the account removes its scans and their findings.
    account_id = account.id
    db.delete(account)
    db.commit()
    assert db.get(CloudScan, scan.id) is None
    assert db.get(CloudFinding, finding.id) is None
    assert (
        db.exec(select(CloudAccount).where(CloudAccount.id == account_id)).first()
        is None
    )


def test_cloud_account_external_id_unique(db: Session, org: Organization) -> None:
    external_id = uuid.uuid4().hex
    db.add(
        CloudAccount(
            org_id=org.id,
            display_name="Account A",
            external_id=external_id,
        )
    )
    db.commit()

    db.add(
        CloudAccount(
            org_id=org.id,
            display_name="Account B (different account, reused external_id)",
            external_id=external_id,
        )
    )
    with pytest.raises(Exception):  # noqa: B017 — IntegrityError from the unique constraint
        db.commit()
    db.rollback()
