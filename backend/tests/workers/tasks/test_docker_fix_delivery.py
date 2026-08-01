"""Unit tests for the docker_fix_delivery Celery task."""

import uuid
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import Session

from app.models import (
    DockerFix,
    DockerTarget,
    LLMProvider,
    Organization,
    PullRequest,
    PullRequestState,
    Repository,
    UserTier,
)
from app.models.enums import FixStatus
from app.services.delivery_pr import docker_fix_branch
from app.workers.tasks.docker_fix_delivery import deliver_docker_fixes


@dataclass
class FakeDockerFile:
    path: str
    content: str


@dataclass
class FakeDeliveryResult:
    pr_url: str | None = "https://github.com/o/r/pull/7"
    error: str | None = None
    extra: dict[str, str] = field(default_factory=dict)


@pytest.fixture()
def org(db: Session) -> Organization:
    item = Organization(name=f"dl-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@pytest.fixture()
def repo(db: Session, org: Organization) -> Repository:
    item = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"dlowner/repo-{uuid.uuid4().hex[:8]}",
        installation_id=52001,
        default_branch="main",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@pytest.fixture()
def target(db: Session, repo: Repository) -> DockerTarget:
    item = DockerTarget(repo_id=repo.id, root_path="")
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _ready_fix(
    db: Session, target: DockerTarget, path: str = "Dockerfile"
) -> DockerFix:
    fix = DockerFix(
        docker_target_id=target.id,
        file_path=path,
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o-mini",
        status=FixStatus.ready,
        full_content="FROM python:3.12-slim\nUSER app\n",
    )
    db.add(fix)
    db.commit()
    db.refresh(fix)
    return fix


def _deliver(target: DockerTarget, result: FakeDeliveryResult, **kwargs: object):
    with (
        patch(
            "app.workers.tasks.docker_fix_delivery._fetch_docker_files",
            return_value=[
                FakeDockerFile(path="Dockerfile", content="FROM python:3.12-slim\n")
            ],
        ),
        patch(
            "app.workers.tasks.docker_fix_delivery._deliver",
            new=AsyncMock(return_value=result),
        ),
    ):
        return deliver_docker_fixes(str(target.id), **kwargs)  # type: ignore[arg-type]


def test_delivery_opens_a_pr_and_marks_fixes_delivered(
    db: Session, target: DockerTarget, repo: Repository
) -> None:
    fix = _ready_fix(db, target)
    result = _deliver(target, FakeDeliveryResult())
    assert result["status"] == "ok"

    db.refresh(fix)
    assert fix.status == FixStatus.delivered
    assert fix.delivered_at is not None
    assert fix.pr_id is not None

    pr = db.get(PullRequest, fix.pr_id)
    assert pr is not None
    # The branch is deterministic per target, so the UI can match an open PR
    # to the target that produced it by name alone.
    assert pr.pr_branch == docker_fix_branch(target.id)
    assert pr.pr_branch.startswith("greensecops/docker-")


def test_a_delivery_error_marks_fixes_failed(db: Session, target: DockerTarget) -> None:
    fix = _ready_fix(db, target)
    result = _deliver(target, FakeDeliveryResult(pr_url=None, error="push rejected"))
    assert result["status"] == "failed"
    db.refresh(fix)
    assert fix.status == FixStatus.failed
    assert fix.error_message == "push rejected"


def test_delivery_needs_an_installation(
    db: Session, target: DockerTarget, repo: Repository
) -> None:
    repo.installation_id = None
    db.add(repo)
    db.commit()
    _ready_fix(db, target)
    result = deliver_docker_fixes(str(target.id))
    assert result == {"status": "skipped", "reason": "no_installation"}


def test_delivery_without_ready_fixes_is_an_error(
    db: Session, target: DockerTarget
) -> None:
    result = deliver_docker_fixes(str(target.id))
    assert result == {"status": "error", "detail": "no_ready_fixes"}


def test_a_previously_closed_pr_blocks_redelivery(
    db: Session, target: DockerTarget, repo: Repository
) -> None:
    """A closed PR is a rejection signal, not an invitation to re-push."""
    db.add(
        PullRequest(
            repo_id=repo.id,
            pr_branch=docker_fix_branch(target.id),
            pr_url="https://github.com/o/r/pull/1",
            pr_state=PullRequestState.closed,
        )
    )
    db.commit()
    _ready_fix(db, target)

    result = deliver_docker_fixes(str(target.id))
    assert result == {"status": "skipped", "reason": "pr_previously_closed"}


def test_force_overrides_a_closed_pr(
    db: Session, target: DockerTarget, repo: Repository
) -> None:
    db.add(
        PullRequest(
            repo_id=repo.id,
            pr_branch=docker_fix_branch(target.id),
            pr_url="https://github.com/o/r/pull/1",
            pr_state=PullRequestState.closed,
        )
    )
    db.commit()
    fix = _ready_fix(db, target)

    result = _deliver(target, FakeDeliveryResult(), force=True)
    assert result["status"] == "ok"
    db.refresh(fix)
    assert fix.status == FixStatus.delivered


def test_missing_target_is_an_error() -> None:
    result = deliver_docker_fixes(str(uuid.uuid4()))
    assert result == {"status": "error", "detail": "docker_target_not_found"}
