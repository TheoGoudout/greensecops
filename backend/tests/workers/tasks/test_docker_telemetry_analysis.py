"""Unit tests for the docker_telemetry_analysis Celery task."""

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import Session, select

from app.models import (
    DockerBuildEnrichment,
    DockerBuildTelemetry,
    Organization,
    Repository,
    UserTier,
)
from app.services.opa.evaluator import CiTelemetryOpaViolation
from app.workers.tasks.docker_telemetry_analysis import (
    _build_document,
    _run_docker_telemetry_analysis_impl,
)


@pytest.fixture()
def org(db: Session) -> Organization:
    item = Organization(name=f"tel-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@pytest.fixture()
def repo(db: Session, org: Organization) -> Repository:
    item = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"telowner/repo-{uuid.uuid4().hex[:8]}",
        installation_id=53001,
        default_branch="main",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@pytest.fixture()
def telemetry(db: Session, repo: Repository) -> DockerBuildTelemetry:
    item = DockerBuildTelemetry(
        repo_id=repo.id,
        workflow_run_id=99,
        image_ref="sha256:abc",
        dockerfile_path="backend/Dockerfile",
        image_size_bytes=2_400_000_000,
        context_size_bytes=900_000_000,
        build_duration_ms=260_000,
        cache_hit_ratio=0.18,
        layers=json.dumps([{"index": 0, "size_bytes": 100, "instruction": "RUN"}]),
        containers=json.dumps([{"name": "api", "oom_killed": True}]),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _violation(slug: str = "oversized_image") -> CiTelemetryOpaViolation:
    return CiTelemetryOpaViolation(
        rule_slug=slug,
        severity="medium",
        category="energy",
        evidence="final image is 2.4 GB",
        recommendation="Split the build into stages.",
    )


def _run(telemetry_id: str, violations: list[Any], **kwargs: Any) -> dict[str, Any]:
    with patch(
        "app.workers.tasks.docker_telemetry_analysis._evaluate",
        new=AsyncMock(return_value=violations),
    ):
        return _run_docker_telemetry_analysis_impl(telemetry_id, **kwargs)


def test_document_shape_matches_what_the_rules_read(
    telemetry: DockerBuildTelemetry,
) -> None:
    doc = _build_document(telemetry, observed_builds=6)
    assert doc["build"]["cache_hit_ratio"] == 0.18
    assert doc["build"]["image_size_bytes"] == 2_400_000_000
    # observed_builds is a property of the build *series*, not of this row, so
    # it rides in from the ingest call rather than being persisted.
    assert doc["build"]["observed_builds"] == 6
    assert doc["containers"] == [{"name": "api", "oom_killed": True}]


def test_document_tolerates_absent_json_blobs(db: Session, repo: Repository) -> None:
    bare = DockerBuildTelemetry(repo_id=repo.id, workflow_run_id=1)
    db.add(bare)
    db.commit()
    db.refresh(bare)
    doc = _build_document(bare, observed_builds=0)
    assert doc["build"]["layers"] == []
    assert doc["containers"] == []


def test_enrichments_are_persisted(
    db: Session, telemetry: DockerBuildTelemetry
) -> None:
    result = _run(str(telemetry.id), [_violation()])
    assert result["status"] == "completed"
    assert result["enrichments"] == 1

    rows = db.exec(
        select(DockerBuildEnrichment).where(
            DockerBuildEnrichment.telemetry_id == telemetry.id
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].rule_slug == "oversized_image"
    assert rows[0].evidence == "final image is 2.4 GB"


def test_reruns_replace_rather_than_duplicate(
    db: Session, telemetry: DockerBuildTelemetry
) -> None:
    # Re-running the same row must be idempotent — the same delete-and-reinsert
    # contract dynamic_analysis has.
    _run(str(telemetry.id), [_violation(), _violation("bloated_build_context")])
    _run(str(telemetry.id), [_violation()])

    rows = db.exec(
        select(DockerBuildEnrichment).where(
            DockerBuildEnrichment.telemetry_id == telemetry.id
        )
    ).all()
    assert len(rows) == 1


def test_an_evaluation_failure_does_not_raise(
    db: Session, telemetry: DockerBuildTelemetry
) -> None:
    with patch(
        "app.workers.tasks.docker_telemetry_analysis._evaluate",
        new=AsyncMock(side_effect=RuntimeError("opa down")),
    ):
        result = _run_docker_telemetry_analysis_impl(str(telemetry.id))
    assert result["status"] == "failed"


def test_missing_telemetry_row_is_an_error() -> None:
    result = _run_docker_telemetry_analysis_impl(str(uuid.uuid4()))
    assert result == {"status": "error", "detail": "telemetry_not_found"}
