"""Unit tests for the terraform_fix_generation Celery task."""

import uuid
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import Session

from app.models import (
    FixStatus,
    IssueCategory,
    IssueSeverity,
    LLMProvider,
    Organization,
    Repository,
    Rule,
    RuleDomain,
    ScanStatus,
    TerraformFinding,
    TerraformFix,
    TerraformRoot,
    TerraformScan,
    UserTier,
)
from app.workers.tasks.terraform_fix_generation import run_terraform_fix_generation

VALID_HCL = 'resource "aws_s3_bucket" "b" {\n  bucket = "x"\n}\n'


@dataclass
class FakeFile:
    path: str
    content: str


@dataclass
class FakeLLMResponse:
    content: str
    prompt_tokens: int = 10
    completion_tokens: int = 20
    run_id: str | None = None


@pytest.fixture()
def repo(db: Session) -> Repository:
    org = Organization(name=f"tffix-{uuid.uuid4().hex[:8]}", tier=UserTier.free)
    db.add(org)
    db.commit()
    db.refresh(org)
    repository = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"tffix/repo-{uuid.uuid4().hex[:8]}",
        installation_id=40001,
        default_branch="main",
    )
    db.add(repository)
    db.commit()
    db.refresh(repository)
    return repository


@pytest.fixture()
def root(db: Session, repo: Repository) -> TerraformRoot:
    r = TerraformRoot(repo_id=repo.id, root_path=f"infra/{uuid.uuid4().hex[:8]}")
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


@pytest.fixture()
def scan(db: Session, root: TerraformRoot) -> TerraformScan:
    s = TerraformScan(terraform_root_id=root.id, status=ScanStatus.completed)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@pytest.fixture()
def rule(db: Session) -> Rule:
    from sqlmodel import select

    r = db.exec(select(Rule).where(Rule.domain == RuleDomain.iac_terraform)).first()
    assert r is not None
    return r


def _finding(
    db: Session, root: TerraformRoot, scan: TerraformScan, rule: Rule
) -> TerraformFinding:
    f = TerraformFinding(
        scan_id=scan.id,
        terraform_root_id=root.id,
        rule_id=rule.id,
        file_path="main.tf",
        fingerprint=uuid.uuid4().hex[:16],
        severity=IssueSeverity.high,
        category=IssueCategory.security,
        message="unencrypted bucket",
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    return f


def _pending_fix(db: Session, root: TerraformRoot) -> TerraformFix:
    fix = TerraformFix(
        terraform_root_id=root.id,
        file_path="main.tf",
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o-mini",
        status=FixStatus.pending,
    )
    db.add(fix)
    db.commit()
    db.refresh(fix)
    return fix


def _patch_fetch(files: list[FakeFile]) -> Any:
    return patch(
        "app.workers.tasks.terraform_fix_generation._fetch_terraform_files",
        return_value=files,
    )


def _patch_llm(content: str) -> Any:
    return patch(
        "app.workers.tasks.terraform_fix_generation._generate_terraform_fix",
        new=AsyncMock(return_value=FakeLLMResponse(content=content)),
    )


def test_no_findings_returns_error(db: Session) -> None:  # noqa: ARG001
    result = run_terraform_fix_generation([str(uuid.uuid4())])
    assert result["status"] == "error"
    assert result["detail"] == "no_findings_found"


def test_no_pending_fix_is_skipped(
    db: Session, root: TerraformRoot, scan: TerraformScan, rule: Rule
) -> None:
    finding = _finding(db, root, scan, rule)
    # No TerraformFix row created → nothing to consume.
    result = run_terraform_fix_generation([str(finding.id)])
    assert result["status"] == "skipped"


def test_success_marks_fix_ready(
    db: Session, root: TerraformRoot, scan: TerraformScan, rule: Rule
) -> None:
    finding = _finding(db, root, scan, rule)
    fix = _pending_fix(db, root)
    llm = f"<full_content>\n{VALID_HCL}</full_content>\n<unfixed>\n</unfixed>"
    with _patch_fetch([FakeFile("main.tf", "old\n")]), _patch_llm(llm):
        result = run_terraform_fix_generation([str(finding.id)])
    assert result["status"] == FixStatus.ready.value
    db.refresh(fix)
    assert fix.status == FixStatus.ready
    assert fix.full_content is not None
    assert "aws_s3_bucket" in fix.full_content


def test_invalid_hcl_marks_fix_failed(
    db: Session, root: TerraformRoot, scan: TerraformScan, rule: Rule
) -> None:
    finding = _finding(db, root, scan, rule)
    fix = _pending_fix(db, root)
    llm = "<full_content>\nthis is ][ not valid hcl {{{\n</full_content>"
    with _patch_fetch([FakeFile("main.tf", "old\n")]), _patch_llm(llm):
        result = run_terraform_fix_generation([str(finding.id)])
    assert result["status"] == FixStatus.failed.value
    db.refresh(fix)
    assert fix.status == FixStatus.failed
    assert fix.error_message


def test_missing_content_marks_fix_failed(
    db: Session, root: TerraformRoot, scan: TerraformScan, rule: Rule
) -> None:
    finding = _finding(db, root, scan, rule)
    fix = _pending_fix(db, root)
    with _patch_fetch([FakeFile("main.tf", "old\n")]), _patch_llm("no block here"):
        result = run_terraform_fix_generation([str(finding.id)])
    assert result["status"] == FixStatus.failed.value
    db.refresh(fix)
    assert fix.status == FixStatus.failed


def test_fetch_failure_marks_fix_failed(
    db: Session, root: TerraformRoot, scan: TerraformScan, rule: Rule
) -> None:
    finding = _finding(db, root, scan, rule)
    fix = _pending_fix(db, root)
    with patch(
        "app.workers.tasks.terraform_fix_generation._fetch_terraform_files",
        side_effect=RuntimeError("github down"),
    ):
        result = run_terraform_fix_generation([str(finding.id)])
    assert result["status"] == "failed"
    db.refresh(fix)
    assert fix.status == FixStatus.failed


def test_file_missing_from_fetch_marks_fix_failed(
    db: Session, root: TerraformRoot, scan: TerraformScan, rule: Rule
) -> None:
    finding = _finding(db, root, scan, rule)
    fix = _pending_fix(db, root)
    with _patch_fetch([FakeFile("other.tf", "x\n")]):
        result = run_terraform_fix_generation([str(finding.id)])
    assert result["status"] == "failed"
    db.refresh(fix)
    assert fix.status == FixStatus.failed
