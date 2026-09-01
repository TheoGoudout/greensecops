"""Unit tests for the docker_fix_generation Celery task."""

import uuid
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import Session, select

from app.models import (
    Category,
    DockerFinding,
    DockerFix,
    DockerScan,
    DockerTarget,
    LLMProvider,
    Organization,
    Repository,
    Rule,
    RuleDomain,
    ScanStatus,
    Severity,
    UserTier,
)
from app.models.enums import FixStatus, ScanTrigger
from app.workers.tasks.docker_fix_generation import (
    INVALID_COMPOSE_ERROR,
    INVALID_DOCKERFILE_ERROR,
    MISSING_CONTENT_ERROR,
    run_docker_fix_generation,
)


@dataclass
class FakeDockerFile:
    path: str
    content: str


@dataclass
class FakeLLMResponse:
    content: str
    prompt_tokens: int = 10
    completion_tokens: int = 20
    model: str = "gpt-4o-mini"
    run_id: str | None = None


_DOCKERFILE = 'FROM python:3.12-slim\nCMD ["python"]\n'
_FIXED_DOCKERFILE = 'FROM python:3.12-slim\nUSER app\nCMD ["python"]\n'
_COMPOSE = "services:\n  api:\n    image: app:1.0\n"


@pytest.fixture()
def org(db: Session) -> Organization:
    item = Organization(name=f"fx-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@pytest.fixture()
def repo(db: Session, org: Organization) -> Repository:
    item = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"fxowner/repo-{uuid.uuid4().hex[:8]}",
        installation_id=51001,
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


@pytest.fixture()
def rule(db: Session) -> Rule:
    item = db.exec(
        select(Rule).where(Rule.domain == RuleDomain.container_docker)
    ).first()
    assert item is not None
    return item


def _finding(
    db: Session, target: DockerTarget, rule: Rule, file_path: str
) -> DockerFinding:
    scan = DockerScan(
        docker_target_id=target.id,
        status=ScanStatus.completed,
        triggered_by=ScanTrigger.manual,
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)
    finding = DockerFinding(
        scan_id=scan.id,
        docker_target_id=target.id,
        rule_id=rule.id,
        file_path=file_path,
        fingerprint=uuid.uuid4().hex[:16],
        severity=Severity.high,
        category=Category.security,
        message="runs as root",
    )
    db.add(finding)
    db.commit()
    db.refresh(finding)
    return finding


def _pending_fix(db: Session, target: DockerTarget, file_path: str) -> DockerFix:
    fix = DockerFix(
        docker_target_id=target.id,
        file_path=file_path,
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o-mini",
        status=FixStatus.pending,
    )
    db.add(fix)
    db.commit()
    db.refresh(fix)
    return fix


def _run(
    finding: DockerFinding, llm_content: str, source: str, path: str
) -> dict[str, Any]:
    with (
        patch(
            "app.workers.tasks.docker_fix_generation._fetch_docker_files",
            return_value=[FakeDockerFile(path=path, content=source)],
        ),
        patch(
            "app.services.file_fix_generation._generate",
            new=AsyncMock(return_value=FakeLLMResponse(content=llm_content)),
        ),
    ):
        return run_docker_fix_generation([str(finding.id)])


def test_generation_stores_a_valid_rewrite(
    db: Session, target: DockerTarget, rule: Rule
) -> None:
    finding = _finding(db, target, rule, "Dockerfile")
    fix = _pending_fix(db, target, "Dockerfile")
    result = _run(
        finding,
        f"<full_content>\n{_FIXED_DOCKERFILE}</full_content>\n<unfixed>\n</unfixed>",
        _DOCKERFILE,
        "Dockerfile",
    )
    assert result["status"] == FixStatus.ready.value
    db.refresh(fix)
    assert fix.full_content == _FIXED_DOCKERFILE
    assert fix.prompt_tokens == 10


def test_an_unparseable_dockerfile_rewrite_is_discarded(
    db: Session, target: DockerTarget, rule: Rule
) -> None:
    """The gate that stops delivery pushing a broken build to a real branch."""
    finding = _finding(db, target, rule, "Dockerfile")
    fix = _pending_fix(db, target, "Dockerfile")
    result = _run(
        finding,
        "<full_content>\n# only a comment, no instructions\n</full_content>",
        _DOCKERFILE,
        "Dockerfile",
    )
    assert result["status"] == FixStatus.failed.value
    db.refresh(fix)
    assert fix.error_message == INVALID_DOCKERFILE_ERROR
    assert fix.full_content is None


def test_an_invalid_compose_rewrite_is_discarded(
    db: Session, target: DockerTarget, rule: Rule
) -> None:
    finding = _finding(db, target, rule, "compose.yml")
    fix = _pending_fix(db, target, "compose.yml")
    result = _run(
        finding,
        "<full_content>\nservices: [unclosed\n</full_content>",
        _COMPOSE,
        "compose.yml",
    )
    assert result["status"] == FixStatus.failed.value
    db.refresh(fix)
    assert fix.error_message == INVALID_COMPOSE_ERROR


def test_a_compose_rewrite_is_validated_as_yaml_not_as_a_dockerfile(
    db: Session, target: DockerTarget, rule: Rule
) -> None:
    """The validator must switch on the file kind, not assume Dockerfile.

    Valid Compose YAML would fail a Dockerfile parse and vice versa, so a
    single hard-coded validator would reject every rewrite of one kind.
    """
    finding = _finding(db, target, rule, "compose.yml")
    fix = _pending_fix(db, target, "compose.yml")
    fixed = "services:\n  api:\n    image: app:1.0\n    restart: unless-stopped\n"
    result = _run(
        finding, f"<full_content>\n{fixed}</full_content>", _COMPOSE, "compose.yml"
    )
    assert result["status"] == FixStatus.ready.value
    db.refresh(fix)
    assert fix.full_content == fixed


def test_a_response_without_content_fails(
    db: Session, target: DockerTarget, rule: Rule
) -> None:
    finding = _finding(db, target, rule, "Dockerfile")
    fix = _pending_fix(db, target, "Dockerfile")
    result = _run(finding, "I could not do that.", _DOCKERFILE, "Dockerfile")
    assert result["status"] == FixStatus.failed.value
    db.refresh(fix)
    assert fix.error_message == MISSING_CONTENT_ERROR


def test_a_file_that_vanished_fails_the_fix(
    db: Session, target: DockerTarget, rule: Rule
) -> None:
    finding = _finding(db, target, rule, "Dockerfile")
    fix = _pending_fix(db, target, "Dockerfile")
    with patch(
        "app.workers.tasks.docker_fix_generation._fetch_docker_files",
        return_value=[],
    ):
        result = run_docker_fix_generation([str(finding.id)])
    assert result["status"] == "failed"
    db.refresh(fix)
    assert fix.status == FixStatus.failed


def test_without_a_pending_row_the_task_is_a_no_op(
    db: Session, target: DockerTarget, rule: Rule
) -> None:
    # The route creates the pending fix; a task that arrives without one must
    # not invent work.
    finding = _finding(db, target, rule, "Dockerfile")
    result = run_docker_fix_generation([str(finding.id)])
    assert result == {"status": "skipped", "detail": "no_pending_fix"}


def test_unknown_finding_ids_are_an_error() -> None:
    result = run_docker_fix_generation([str(uuid.uuid4())])
    assert result == {"status": "error", "detail": "no_findings_found"}


class _CapturingProvider:
    """Stands in for a real provider so the prompt is genuinely built.

    Every other test here patches ``_generate``, which skips prompt building
    entirely — and prompt building is the seam where the findings, by then
    detached from the task's closed session, get read.
    """

    def __init__(self, content: str, captured: dict[str, str]) -> None:
        self._content = content
        self._captured = captured

    async def generate(self, system_prompt: str, user_prompt: str) -> FakeLLMResponse:
        self._captured["system"] = system_prompt
        self._captured["user"] = user_prompt
        return FakeLLMResponse(content=self._content)


def test_prompt_reads_findings_that_outlived_their_session(
    db: Session, target: DockerTarget, rule: Rule
) -> None:
    """The task's session closes before the prompt is built, so the findings
    reach it detached. ``finding.rule.slug`` must still resolve — a lazy load
    at that point raises DetachedInstanceError and fails the fix."""
    rule_slug = rule.slug
    finding = _finding(db, target, rule, "Dockerfile")
    _pending_fix(db, target, "Dockerfile")
    captured: dict[str, str] = {}
    llm_content = (
        f"<full_content>\n{_FIXED_DOCKERFILE}</full_content>\n<unfixed>\n</unfixed>"
    )
    with (
        patch(
            "app.workers.tasks.docker_fix_generation._fetch_docker_files",
            return_value=[FakeDockerFile(path="Dockerfile", content=_DOCKERFILE)],
        ),
        patch(
            "app.services.llm.catalog.get_provider",
            return_value=_CapturingProvider(llm_content, captured),
        ),
    ):
        result = run_docker_fix_generation([str(finding.id)])

    assert result["status"] == FixStatus.ready.value
    assert f"rule: {rule_slug}" in captured["user"]
    assert "runs as root" in captured["user"]


def test_prompt_names_the_repository_the_image_is_built_from(
    db: Session, target: DockerTarget, repo: Repository, rule: Rule
) -> None:
    """The OCI annotation has to point at *this* repository.

    Nothing in the prompt named it, so the model wrote the URL from the rule's
    own example and every fixed image claimed to come from
    `github.com/example/app`.
    """
    full_name = repo.full_name
    finding = _finding(db, target, rule, "Dockerfile")
    _pending_fix(db, target, "Dockerfile")
    captured: dict[str, str] = {}
    llm_content = (
        f"<full_content>\n{_FIXED_DOCKERFILE}</full_content>\n<unfixed>\n</unfixed>"
    )
    with (
        patch(
            "app.workers.tasks.docker_fix_generation._fetch_docker_files",
            return_value=[FakeDockerFile(path="Dockerfile", content=_DOCKERFILE)],
        ),
        patch(
            "app.services.llm.catalog.get_provider",
            return_value=_CapturingProvider(llm_content, captured),
        ),
    ):
        result = run_docker_fix_generation([str(finding.id)])

    assert result["status"] == FixStatus.ready.value
    assert f"https://github.com/{full_name}" in captured["user"]
    assert "**Repository**" in captured["user"]


def test_prompt_offers_digests_resolved_for_the_file_being_fixed(
    db: Session, target: DockerTarget, rule: Rule
) -> None:
    """The digests come from the content the model is about to rewrite.

    Resolved at fix time rather than read off the scan: the rewrite pins what
    the tag points at now, and a digest recorded days ago may not be that.
    """
    digest = "sha256:" + "ef" * 32
    finding = _finding(db, target, rule, "Dockerfile")
    _pending_fix(db, target, "Dockerfile")
    captured: dict[str, str] = {}
    llm_content = (
        f"<full_content>\n{_FIXED_DOCKERFILE}</full_content>\n<unfixed>\n</unfixed>"
    )
    with (
        patch(
            "app.workers.tasks.docker_fix_generation._fetch_docker_files",
            return_value=[FakeDockerFile(path="Dockerfile", content=_DOCKERFILE)],
        ),
        patch(
            "app.workers.tasks.docker_fix_generation.resolve_base_image_digests",
            new=AsyncMock(return_value={"node:latest": digest}),
        ) as resolve,
        patch(
            "app.services.llm.catalog.get_provider",
            return_value=_CapturingProvider(llm_content, captured),
        ),
    ):
        result = run_docker_fix_generation([str(finding.id)])

    assert result["status"] == FixStatus.ready.value
    assert f"node:latest@{digest}" in captured["user"]
    # Resolved from the parsed Dockerfile, so it sees the real FROM lines.
    resolve.assert_awaited_once()


def test_a_registry_outage_costs_the_digests_not_the_fix(
    db: Session, target: DockerTarget, rule: Rule
) -> None:
    """Everything else in the file is still fixable when a lookup fails."""
    finding = _finding(db, target, rule, "Dockerfile")
    _pending_fix(db, target, "Dockerfile")
    captured: dict[str, str] = {}
    llm_content = (
        f"<full_content>\n{_FIXED_DOCKERFILE}</full_content>\n<unfixed>\n</unfixed>"
    )
    with (
        patch(
            "app.workers.tasks.docker_fix_generation._fetch_docker_files",
            return_value=[FakeDockerFile(path="Dockerfile", content=_DOCKERFILE)],
        ),
        patch(
            "app.workers.tasks.docker_fix_generation.resolve_base_image_digests",
            new=AsyncMock(side_effect=RuntimeError("registry unreachable")),
        ),
        patch(
            "app.services.llm.catalog.get_provider",
            return_value=_CapturingProvider(llm_content, captured),
        ),
    ):
        result = run_docker_fix_generation([str(finding.id)])

    assert result["status"] == FixStatus.ready.value
    # No digests offered, so the model is told to leave the references alone.
    assert "Verified base image digests" not in captured["user"]
