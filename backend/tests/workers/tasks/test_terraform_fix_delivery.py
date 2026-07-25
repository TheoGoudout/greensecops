"""Unit tests for the terraform_fix_delivery Celery task."""

import uuid
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import Session, select

from app.models import (
    FixStatus,
    Organization,
    PullRequest,
    PullRequestState,
    Repository,
    TerraformFix,
    TerraformRoot,
    UserTier,
)
from app.services.github.fix_delivery import FixDeliveryResult
from app.workers.tasks.terraform_fix_delivery import deliver_terraform_fixes


@dataclass
class FakeFile:
    path: str
    content: str


@pytest.fixture()
def repo(db: Session) -> Repository:
    org = Organization(name=f"tfdel-{uuid.uuid4().hex[:8]}", tier=UserTier.free)
    db.add(org)
    db.commit()
    db.refresh(org)
    repository = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"tfdel/repo-{uuid.uuid4().hex[:8]}",
        installation_id=50001,
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


def _ready_fix(
    db: Session, root: TerraformRoot, content: str = 'resource "x" "y" {}\n'
) -> TerraformFix:
    from app.models import LLMProvider

    fix = TerraformFix(
        terraform_root_id=root.id,
        file_path="main.tf",
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o-mini",
        status=FixStatus.ready,
        full_content=content,
    )
    db.add(fix)
    db.commit()
    db.refresh(fix)
    return fix


def _patch_deliver(result: FixDeliveryResult) -> Any:
    return patch(
        "app.workers.tasks.terraform_fix_delivery._deliver",
        new=AsyncMock(return_value=result),
    )


def _patch_fetch(files: list[FakeFile]) -> Any:
    return patch(
        "app.workers.tasks.terraform_fix_delivery._fetch_terraform_files",
        return_value=files,
    )


def test_root_not_found_returns_error(db: Session) -> None:  # noqa: ARG001
    result = deliver_terraform_fixes(terraform_root_id=str(uuid.uuid4()))
    assert result["status"] == "error"
    assert result["detail"] == "terraform_root_not_found"


def test_no_installation_is_skipped(
    db: Session, repo: Repository, root: TerraformRoot
) -> None:
    repo.installation_id = None
    db.add(repo)
    db.commit()
    _ready_fix(db, root)
    result = deliver_terraform_fixes(terraform_root_id=str(root.id))
    assert result["status"] == "skipped"
    assert result["reason"] == "no_installation"


def test_no_ready_fixes_returns_error(db: Session, root: TerraformRoot) -> None:
    result = deliver_terraform_fixes(terraform_root_id=str(root.id))
    assert result["status"] == "error"
    assert result["detail"] == "no_ready_fixes"


def test_success_creates_pr_and_marks_delivered(
    db: Session, root: TerraformRoot
) -> None:
    fix = _ready_fix(db, root)
    pr_url = "https://github.com/acme/infra/pull/7"
    with (
        _patch_fetch([FakeFile("main.tf", "old\n")]),
        _patch_deliver(FixDeliveryResult(pr_url=pr_url)),
    ):
        result = deliver_terraform_fixes(terraform_root_id=str(root.id))
    assert result["status"] == "ok"
    db.refresh(fix)
    assert fix.status == FixStatus.delivered
    assert fix.delivered_at is not None
    pr = db.exec(select(PullRequest).where(PullRequest.repo_id == root.repo_id)).first()
    assert pr is not None
    assert pr.pr_url == pr_url
    assert fix.pr_id == pr.id


def test_delivery_error_marks_fix_failed(db: Session, root: TerraformRoot) -> None:
    fix = _ready_fix(db, root)
    with (
        _patch_fetch([FakeFile("main.tf", "old\n")]),
        _patch_deliver(FixDeliveryResult(error="boom")),
    ):
        result = deliver_terraform_fixes(terraform_root_id=str(root.id))
    assert result["status"] == "failed"
    db.refresh(fix)
    assert fix.status == FixStatus.failed
    assert fix.error_message == "boom"


def test_closed_pr_blocks_unforced_delivery(
    db: Session, repo: Repository, root: TerraformRoot
) -> None:
    from app.services.delivery_pr import tf_fix_branch

    _ready_fix(db, root)
    # A closed PR on the root's branch is a rejection signal.
    pr = PullRequest(
        repo_id=repo.id,
        pr_branch=tf_fix_branch(root.id),
        pr_state=PullRequestState.closed,
    )
    db.add(pr)
    db.commit()
    result = deliver_terraform_fixes(terraform_root_id=str(root.id))
    assert result["status"] == "skipped"
    assert result["reason"] == "pr_previously_closed"
