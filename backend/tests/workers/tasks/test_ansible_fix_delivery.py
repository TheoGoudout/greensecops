"""Unit tests for the ansible_fix_delivery Celery task.

Delivery itself is engine-agnostic — ``services/file_fix_delivery.py`` does the
work and is already covered against the other engines. What these assert is
that the Ansible task is wired into it correctly: the right spec, the right
target-not-found string, and the branch name the delivery PR is opened on.
"""

import uuid
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import Session, select

from app.models import (
    AnsibleFix,
    AnsibleProject,
    FixStatus,
    LLMProvider,
    Organization,
    PullRequest,
    PullRequestState,
    Repository,
    UserTier,
)
from app.services.github.fix_delivery import FixDeliveryResult
from app.workers.tasks.ansible_fix_delivery import deliver_ansible_fixes

_FILE = "roles/docker/tasks/main.yml"
_CONTENT = """---
- name: Log in to ECR
  ansible.builtin.shell:
    cmd: docker login {{ registry | quote }}
  changed_when: false
"""


@dataclass
class FakeFile:
    path: str
    content: str


@pytest.fixture()
def repo(db: Session) -> Repository:
    org = Organization(name=f"ansdel-{uuid.uuid4().hex[:8]}", tier=UserTier.free)
    db.add(org)
    db.commit()
    db.refresh(org)
    repository = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"ansdel/repo-{uuid.uuid4().hex[:8]}",
        installation_id=50001,
        default_branch="main",
    )
    db.add(repository)
    db.commit()
    db.refresh(repository)
    return repository


@pytest.fixture()
def project(db: Session, repo: Repository) -> AnsibleProject:
    p = AnsibleProject(repo_id=repo.id, root_path=f"infra/{uuid.uuid4().hex[:8]}")
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _ready_fix(
    db: Session, project: AnsibleProject, content: str = _CONTENT
) -> AnsibleFix:
    fix = AnsibleFix(
        ansible_project_id=project.id,
        file_path=_FILE,
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
        "app.services.file_fix_delivery._deliver",
        new=AsyncMock(return_value=result),
    )


def _patch_fetch(files: list[FakeFile]) -> Any:
    return patch(
        "app.workers.tasks.ansible_fix_delivery._fetch_ansible_files",
        return_value=files,
    )


def test_project_not_found_returns_error(db: Session) -> None:
    result = deliver_ansible_fixes(ansible_project_id=str(uuid.uuid4()))
    assert result["status"] == "error"
    assert result["detail"] == "ansible_project_not_found"


def test_no_installation_is_skipped(
    db: Session, repo: Repository, project: AnsibleProject
) -> None:
    repo.installation_id = None
    db.add(repo)
    db.commit()
    _ready_fix(db, project)
    result = deliver_ansible_fixes(ansible_project_id=str(project.id))
    assert result["status"] == "skipped"
    assert result["reason"] == "no_installation"


def test_no_ready_fixes_returns_error(db: Session, project: AnsibleProject) -> None:
    result = deliver_ansible_fixes(ansible_project_id=str(project.id))
    assert result["status"] == "error"
    assert result["detail"] == "no_ready_fixes"


def test_success_creates_pr_and_marks_delivered(
    db: Session, project: AnsibleProject
) -> None:
    fix = _ready_fix(db, project)
    pr_url = "https://github.com/acme/infra/pull/7"
    with (
        _patch_fetch([FakeFile(_FILE, "old\n")]),
        _patch_deliver(FixDeliveryResult(pr_url=pr_url)),
    ):
        result = deliver_ansible_fixes(ansible_project_id=str(project.id))

    assert result["status"] == "ok"
    db.refresh(fix)
    assert fix.status == FixStatus.delivered
    assert fix.delivered_at is not None
    pr = db.exec(
        select(PullRequest).where(PullRequest.repo_id == project.repo_id)
    ).first()
    assert pr is not None
    assert pr.pr_url == pr_url
    assert fix.pr_id == pr.id


def test_delivery_error_marks_fix_failed(db: Session, project: AnsibleProject) -> None:
    fix = _ready_fix(db, project)
    with (
        _patch_fetch([FakeFile(_FILE, "old\n")]),
        _patch_deliver(FixDeliveryResult(error="boom")),
    ):
        result = deliver_ansible_fixes(ansible_project_id=str(project.id))

    assert result["status"] == "failed"
    db.refresh(fix)
    assert fix.status == FixStatus.failed
    assert fix.error_message == "boom"


def test_closed_pr_blocks_unforced_delivery(
    db: Session, repo: Repository, project: AnsibleProject
) -> None:
    from app.services.delivery_pr import ansible_fix_branch

    _ready_fix(db, project)
    # A closed PR on this project's branch is a rejection signal: reopening the
    # same fix would be arguing with the user.
    pr = PullRequest(
        repo_id=repo.id,
        pr_branch=ansible_fix_branch(project.id),
        pr_state=PullRequestState.closed,
    )
    db.add(pr)
    db.commit()
    result = deliver_ansible_fixes(ansible_project_id=str(project.id))
    assert result["status"] == "skipped"
    assert result["reason"] == "pr_previously_closed"
