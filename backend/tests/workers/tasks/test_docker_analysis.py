"""Unit tests for the docker_analysis Celery task (extracted impl function)."""

import uuid
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import Session, col, select

from app.models import (
    Category,
    DockerFinding,
    DockerScan,
    DockerTarget,
    FindingStatus,
    Organization,
    Repository,
    Rule,
    RuleDomain,
    ScanStatus,
    Severity,
    UserTier,
)
from app.services.opa.evaluator import DockerOpaViolation, OpaUnavailableError
from app.workers.tasks.docker_analysis import (
    DockerFetchError,
    _run_docker_scan_impl,
)


@dataclass
class FakeDockerFile:
    path: str
    content: str
    content_hash: str = ""
    sha: str = ""


@pytest.fixture()
def org(db: Session) -> Organization:
    organization = Organization(
        name=f"dk-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free
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
        full_name=f"dkowner/repo-{uuid.uuid4().hex[:8]}",
        installation_id=40001,
        default_branch="main",
    )
    db.add(repository)
    db.commit()
    db.refresh(repository)
    return repository


@pytest.fixture()
def target(db: Session, repo: Repository) -> DockerTarget:
    item = DockerTarget(repo_id=repo.id, root_path=f"svc/{uuid.uuid4().hex[:8]}")
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@pytest.fixture()
def rule(db: Session) -> Rule:
    existing = db.exec(
        select(Rule).where(Rule.slug == "container_runs_as_root")
    ).first()
    if existing:
        return existing
    item = Rule(
        slug="container_runs_as_root",
        domain=RuleDomain.container_docker,
        category=Category.security,
        severity=Severity.high,
        severity_weight=1.8,
        title="Container image runs as root",
        description="test",
        enabled=True,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


_DOCKERFILE = 'FROM python:3.12-slim\nCMD ["python"]\n'


def _violation(**overrides: Any) -> DockerOpaViolation:
    defaults: dict[str, Any] = {
        "rule_slug": "container_runs_as_root",
        "severity": "high",
        "category": "security",
        "message": "runs as root",
        "file_path": "Dockerfile",
    }
    defaults.update(overrides)
    return DockerOpaViolation(**defaults)


def _run(
    target: DockerTarget,
    files: list[FakeDockerFile],
    violations: list[DockerOpaViolation],
    **kwargs: Any,
) -> dict[str, Any]:
    with (
        patch(
            "app.workers.tasks.docker_analysis._fetch_docker_files",
            return_value=files,
        ),
        patch(
            "app.workers.tasks.docker_analysis._evaluate",
            new=AsyncMock(return_value=violations),
        ),
    ):
        return _run_docker_scan_impl(str(target.id), **kwargs)


def test_scan_persists_findings(db: Session, target: DockerTarget, rule: Rule) -> None:
    result = _run(
        target,
        [FakeDockerFile(path="Dockerfile", content=_DOCKERFILE)],
        [_violation(stage_name="runtime", line_start=1, line_end=2)],
    )
    assert result["status"] == "done"
    assert result["findings"] == 1

    findings = db.exec(
        select(DockerFinding).where(DockerFinding.docker_target_id == target.id)
    ).all()
    assert len(findings) == 1
    assert findings[0].file_path == "Dockerfile"
    assert findings[0].stage_name == "runtime"
    assert findings[0].severity == Severity.high


def test_scan_reports_no_targets_when_no_docker_files(
    db: Session, target: DockerTarget
) -> None:
    result = _run(target, [], [])
    assert result["status"] == "no_targets"
    scan = db.get(DockerScan, uuid.UUID(str(result["scan_id"])))
    assert scan is not None
    assert scan.status == ScanStatus.no_targets


def test_score_is_the_mean_of_per_file_scores(
    db: Session, target: DockerTarget, rule: Rule
) -> None:
    """The whole reason this engine doesn't pool violations like Terraform.

    Two files, four high-severity findings, all in one of them. Pooled, the
    penalty is 4 * 10 * 1.8 = 72 → score 28. Averaged per file, the dirty file
    scores 28 and the clean one 100, so the target scores 64. A target is N
    independent files, and pooling would give any repo with a handful of
    Dockerfiles an F regardless of how many of them are fine.
    """
    files = [
        FakeDockerFile(path="a/Dockerfile", content=_DOCKERFILE),
        FakeDockerFile(path="b/Dockerfile", content=_DOCKERFILE),
    ]
    violations = [
        _violation(file_path="a/Dockerfile", discriminator=f"d{i}") for i in range(4)
    ]
    result = _run(target, files, violations)

    assert result["files"] == 2
    assert result["score"] == pytest.approx(64.0)
    scan = db.get(DockerScan, uuid.UUID(str(result["scan_id"])))
    assert scan is not None
    assert scan.file_count == 2


def test_clean_files_count_towards_the_mean(
    db: Session, target: DockerTarget, rule: Rule
) -> None:
    """A file with no findings must be in the denominator.

    Otherwise the mean is taken over offenders only, and a target where one
    file of twenty is bad scores identically to one where the only file is
    bad.
    """
    many_clean = [
        FakeDockerFile(path=f"svc{i}/Dockerfile", content=_DOCKERFILE) for i in range(9)
    ]
    files = [FakeDockerFile(path="bad/Dockerfile", content=_DOCKERFILE), *many_clean]
    result = _run(target, files, [_violation(file_path="bad/Dockerfile")])

    assert result["files"] == 10
    # One file at 82, nine at 100.
    assert result["score"] == pytest.approx(98.2)
    assert result["grade"] == "A+++"


def test_rescan_reopens_a_resolved_finding(
    db: Session, target: DockerTarget, rule: Rule
) -> None:
    files = [FakeDockerFile(path="Dockerfile", content=_DOCKERFILE)]
    _run(target, files, [_violation()])
    # Second scan sees nothing: the finding resolves.
    _run(target, files, [])
    finding = db.exec(
        select(DockerFinding).where(DockerFinding.docker_target_id == target.id)
    ).one()
    db.refresh(finding)
    assert finding.resolved_at is not None
    assert finding.status == FindingStatus.resolved

    # Third scan sees it again: same row reopens rather than duplicating.
    _run(target, files, [_violation()])
    findings = db.exec(
        select(DockerFinding).where(DockerFinding.docker_target_id == target.id)
    ).all()
    assert len(findings) == 1
    db.refresh(findings[0])
    assert findings[0].resolved_at is None


def test_two_findings_of_one_rule_in_a_file_stay_distinct(
    db: Session, target: DockerTarget, rule: Rule
) -> None:
    result = _run(
        target,
        [FakeDockerFile(path="compose.yml", content="services: {}\n")],
        [
            _violation(
                file_path="compose.yml", service_name="api", discriminator="api"
            ),
            _violation(file_path="compose.yml", service_name="db", discriminator="db"),
        ],
    )
    assert result["findings"] == 2
    findings = db.exec(
        select(DockerFinding).where(DockerFinding.docker_target_id == target.id)
    ).all()
    assert {f.service_name for f in findings} == {"api", "db"}


def test_unknown_rule_slug_is_dropped_with_a_warning(
    db: Session, target: DockerTarget, rule: Rule, caplog: Any
) -> None:
    import logging

    with caplog.at_level(logging.WARNING, logger="app.workers.tasks.docker_analysis"):
        result = _run(
            target,
            [FakeDockerFile(path="Dockerfile", content=_DOCKERFILE)],
            [_violation(rule_slug="a_rule_with_no_row")],
        )
    assert result["findings"] == 0
    assert any("unknown rule slug" in rec.message for rec in caplog.records)


def test_opa_outage_marks_the_scan_transiently_failed(
    db: Session, target: DockerTarget
) -> None:
    # A perfect score must never be reported just because OPA is down.
    with (
        patch(
            "app.workers.tasks.docker_analysis._fetch_docker_files",
            return_value=[FakeDockerFile(path="Dockerfile", content=_DOCKERFILE)],
        ),
        patch(
            "app.workers.tasks.docker_analysis._evaluate",
            new=AsyncMock(side_effect=OpaUnavailableError("down")),
        ),
    ):
        result = _run_docker_scan_impl(str(target.id))

    assert result["status"] == "failed"
    scan = db.get(DockerScan, uuid.UUID(str(result["scan_id"])))
    assert scan is not None
    assert scan.status == ScanStatus.failed
    assert scan.failure_kind is not None
    assert scan.failure_kind.value == "transient"


def test_fetch_failure_raises_for_retry(db: Session, target: DockerTarget) -> None:
    with patch(
        "app.workers.tasks.docker_analysis._fetch_docker_files",
        side_effect=RuntimeError("502 from GitHub"),
    ):
        with pytest.raises(DockerFetchError):
            _run_docker_scan_impl(str(target.id))


def test_missing_target_returns_an_error(db: Session) -> None:
    result = _run_docker_scan_impl(str(uuid.uuid4()))
    assert result == {"status": "error", "detail": "docker_target_not_found"}


def test_commit_sha_advances_the_target_cursor(
    db: Session, target: DockerTarget, rule: Rule
) -> None:
    _run(
        target,
        [FakeDockerFile(path="Dockerfile", content=_DOCKERFILE)],
        [],
        commit_sha="a" * 40,
        branch="main",
    )
    db.refresh(target)
    assert target.last_scanned_head_sha == "a" * 40
    assert target.last_scanned_at is not None


def test_disabled_rule_findings_are_ignored(
    db: Session, target: DockerTarget, rule: Rule
) -> None:
    rule.enabled = False
    db.add(rule)
    db.commit()
    try:
        result = _run(
            target,
            [FakeDockerFile(path="Dockerfile", content=_DOCKERFILE)],
            [_violation()],
        )
        assert result["findings"] == 0
    finally:
        rule.enabled = True
        db.add(rule)
        db.commit()


def test_findings_are_scoped_to_their_scan(
    db: Session, target: DockerTarget, rule: Rule
) -> None:
    files = [FakeDockerFile(path="Dockerfile", content=_DOCKERFILE)]
    first = _run(target, files, [_violation()])
    second = _run(target, files, [_violation()])
    finding = db.exec(
        select(DockerFinding)
        .where(DockerFinding.docker_target_id == target.id)
        .where(col(DockerFinding.resolved_at).is_(None))
    ).one()
    db.refresh(finding)
    # The upsert re-points the surviving row at the newest scan.
    assert str(finding.scan_id) == second["scan_id"]
    assert str(finding.scan_id) != first["scan_id"]
