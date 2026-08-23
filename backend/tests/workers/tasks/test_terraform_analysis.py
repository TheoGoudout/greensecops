"""Unit tests for the terraform_analysis Celery task (extracted impl function).

The Terraform handed to the task is real: ``s3.tf`` and ``ec2.tf`` come from
bridgecrewio/terragoat via ``tests/fixtures/terraform/`` (see the README there),
and the resource addresses asserted on are the ones those files actually
declare. Broader coverage of the corpus — every case, every block type, the
recorded rule output — lives in ``test_terraform_analysis_integration.py``.
"""

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import Session, col, select

from app.models import (
    Category,
    FindingStatus,
    Organization,
    Repository,
    Rule,
    RuleDomain,
    ScanStatus,
    Severity,
    TerraformFinding,
    TerraformRoot,
    TerraformScan,
    UserTier,
)
from app.services.opa.evaluator import OpaUnavailableError, TerraformOpaViolation
from app.workers.tasks.terraform_analysis import (
    TerraformFetchError,
    _run_terraform_scan_impl,
)

_FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "terraform"

# Real files from the vendored corpus. `s3.tf` declares aws_s3_bucket.data;
# `ec2.tf` declares aws_security_group.web-node — the addresses used below.
_S3_TF = (_FIXTURES / "terragoat_aws" / "s3.tf").read_text()
_EC2_TF = (_FIXTURES / "terragoat_aws" / "ec2.tf").read_text()
# The hardened registry module, which the rule suite finds nothing in.
_HARDENED_TF = (_FIXTURES / "terraform_aws_security_group" / "main.tf").read_text()


@dataclass
class FakeTerraformFile:
    path: str
    content: str
    content_hash: str = ""
    sha: str = ""


@pytest.fixture()
def org(db: Session) -> Organization:
    organization = Organization(
        name=f"tf-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free
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
        full_name=f"tfowner/repo-{uuid.uuid4().hex[:8]}",
        installation_id=30001,
        default_branch="main",
    )
    db.add(repository)
    db.commit()
    db.refresh(repository)
    return repository


@pytest.fixture()
def terraform_root(db: Session, repo: Repository) -> TerraformRoot:
    root = TerraformRoot(repo_id=repo.id, root_path=f"infra/{uuid.uuid4().hex[:8]}")
    db.add(root)
    db.commit()
    db.refresh(root)
    return root


@pytest.fixture()
def seeded_terraform_rule(db: Session) -> Rule:
    rule = db.exec(select(Rule).where(Rule.domain == RuleDomain.iac_terraform)).first()
    assert rule is not None, (
        "No seeded Terraform rules found — init_db may not have run"
    )
    return rule


def _patch_fetch(files: list[FakeTerraformFile]) -> Any:
    return patch(
        "app.workers.tasks.terraform_analysis._fetch_terraform_files",
        return_value=files,
    )


def _patch_evaluate(violations: list[TerraformOpaViolation]) -> Any:
    return patch(
        "app.workers.tasks.terraform_analysis._evaluate",
        new=AsyncMock(return_value=violations),
    )


def test_terraform_root_not_found_returns_error(db: Session) -> None:
    result = _run_terraform_scan_impl(str(uuid.uuid4()))
    assert result["status"] == "error"
    assert result["detail"] == "terraform_root_not_found"


def test_no_files_returns_no_targets(
    db: Session, terraform_root: TerraformRoot
) -> None:
    with _patch_fetch([]):
        result = _run_terraform_scan_impl(str(terraform_root.id))

    assert result["status"] == "no_targets"
    scan = db.get(TerraformScan, uuid.UUID(str(result["scan_id"])))
    assert scan is not None
    assert scan.status == ScanStatus.no_targets


def test_fetch_error_raises_terraform_fetch_error(
    db: Session,
    terraform_root: TerraformRoot,
) -> None:
    with (
        patch(
            "app.workers.tasks.terraform_analysis._fetch_terraform_files",
            side_effect=RuntimeError("github down"),
        ),
        pytest.raises(TerraformFetchError),
    ):
        _run_terraform_scan_impl(str(terraform_root.id))


def test_opa_unavailable_marks_scan_failed_transient(
    db: Session, terraform_root: TerraformRoot
) -> None:
    files = [FakeTerraformFile(path="s3.tf", content=_S3_TF)]
    with (
        _patch_fetch(files),
        patch(
            "app.workers.tasks.terraform_analysis._evaluate",
            new=AsyncMock(side_effect=OpaUnavailableError("opa down")),
        ),
    ):
        result = _run_terraform_scan_impl(str(terraform_root.id))

    assert result["status"] == "failed"
    scan = db.get(TerraformScan, uuid.UUID(str(result["scan_id"])))
    assert scan is not None
    assert scan.status == ScanStatus.failed
    from app.models import ScanFailureKind

    assert scan.failure_kind == ScanFailureKind.transient


def test_creates_finding_and_computes_score(
    db: Session, terraform_root: TerraformRoot, seeded_terraform_rule: Rule
) -> None:
    files = [FakeTerraformFile(path="s3.tf", content=_S3_TF)]
    violation = TerraformOpaViolation(
        rule_slug=seeded_terraform_rule.slug,
        severity=seeded_terraform_rule.severity.value,
        category=seeded_terraform_rule.category.value,
        message="something is wrong",
        resource_address="aws_s3_bucket.data",
        file_path="s3.tf",
        # The real span of the aws_s3_bucket "data" block in the vendored file.
        line_start=1,
        line_end=21,
    )
    with _patch_fetch(files), _patch_evaluate([violation]):
        result = _run_terraform_scan_impl(str(terraform_root.id))

    assert result["status"] == "done"
    assert result["findings"] == 1
    assert isinstance(result["score"], float)
    assert result["score"] < 100.0

    findings = db.exec(
        select(TerraformFinding).where(
            TerraformFinding.terraform_root_id == terraform_root.id
        )
    ).all()
    assert len(findings) == 1
    assert findings[0].resource_address == "aws_s3_bucket.data"
    assert findings[0].file_path == "s3.tf"
    # Source line span from the violation is persisted (spec #3).
    assert findings[0].line_start == 1
    assert findings[0].line_end == 21
    # A file directly in the root has no module prefix.
    assert findings[0].module_path is None
    assert findings[0].terraform_address == "aws_s3_bucket.data"
    assert findings[0].status == FindingStatus.open

    db.refresh(terraform_root)
    assert terraform_root.last_scanned_at is not None


def test_finding_in_submodule_dir_gets_module_path_and_address(
    db: Session, terraform_root: TerraformRoot, seeded_terraform_rule: Rule
) -> None:
    # A resource whose file lives in a subdirectory of the root is attributed
    # to that directory as its module path, and its terraform_address carries
    # the module prefix (spec #9).
    sub_file = f"{terraform_root.root_path}/modules/network/ec2.tf"
    files = [FakeTerraformFile(path=sub_file, content=_EC2_TF)]
    violation = TerraformOpaViolation(
        rule_slug=seeded_terraform_rule.slug,
        severity=seeded_terraform_rule.severity.value,
        category=seeded_terraform_rule.category.value,
        message="something is wrong",
        resource_address="aws_security_group.web-node",
        file_path=sub_file,
        # The real span of the aws_security_group "web-node" block.
        line_start=77,
        line_end=115,
    )
    with _patch_fetch(files), _patch_evaluate([violation]):
        result = _run_terraform_scan_impl(str(terraform_root.id))

    assert result["status"] == "done"
    findings = db.exec(
        select(TerraformFinding).where(
            TerraformFinding.terraform_root_id == terraform_root.id
        )
    ).all()
    assert len(findings) == 1
    assert findings[0].module_path == "modules/network"
    assert (
        findings[0].terraform_address
        == "module.modules.network.aws_security_group.web-node"
    )
    assert findings[0].line_start == 77
    assert findings[0].line_end == 115


def test_clean_root_scores_100_and_grade_a_plus_plus_plus(
    db: Session, terraform_root: TerraformRoot
) -> None:
    files = [FakeTerraformFile(path="main.tf", content=_HARDENED_TF)]
    with _patch_fetch(files), _patch_evaluate([]):
        result = _run_terraform_scan_impl(str(terraform_root.id))

    assert result["status"] == "done"
    assert result["findings"] == 0
    assert result["score"] == 100.0
    assert result["grade"] == "A+++"


def test_unknown_rule_slug_is_skipped_not_persisted(
    db: Session, terraform_root: TerraformRoot
) -> None:
    files = [FakeTerraformFile(path="s3.tf", content=_S3_TF)]
    violation = TerraformOpaViolation(
        rule_slug=f"nonexistent-{uuid.uuid4().hex[:8]}",
        severity=Severity.high.value,
        category=Category.security.value,
        message="orphan violation",
        resource_address="aws_s3_bucket.data",
        file_path="s3.tf",
    )
    with _patch_fetch(files), _patch_evaluate([violation]):
        result = _run_terraform_scan_impl(str(terraform_root.id))

    assert result["status"] == "done"
    assert result["findings"] == 0


def test_rescan_resolves_stale_findings_not_seen_again(
    db: Session, terraform_root: TerraformRoot, seeded_terraform_rule: Rule
) -> None:
    files = [FakeTerraformFile(path="s3.tf", content=_S3_TF)]
    violation = TerraformOpaViolation(
        rule_slug=seeded_terraform_rule.slug,
        severity=seeded_terraform_rule.severity.value,
        category=seeded_terraform_rule.category.value,
        message="fixable issue",
        resource_address="aws_s3_bucket.data",
        file_path="s3.tf",
    )
    with _patch_fetch(files), _patch_evaluate([violation]):
        _run_terraform_scan_impl(str(terraform_root.id))

    # Second scan: the violation is gone (user fixed it).
    with _patch_fetch(files), _patch_evaluate([]):
        _run_terraform_scan_impl(str(terraform_root.id))

    findings = db.exec(
        select(TerraformFinding)
        .where(TerraformFinding.terraform_root_id == terraform_root.id)
        .where(col(TerraformFinding.resolved_at).is_not(None))
    ).all()
    assert len(findings) == 1
    assert findings[0].status == FindingStatus.resolved
