"""Tests for the Docker fix prompt, in particular the measured-facts block."""

import uuid

from app.models import DockerBuildEnrichment, DockerFinding
from app.models.enums import Category, Severity
from app.services.llm.docker_fix_prompt import (
    NO_STATIC_FINDINGS_PLACEHOLDER,
    build_docker_fix_prompt,
)


def _finding(message: str) -> DockerFinding:
    return DockerFinding(
        scan_id=uuid.uuid4(),
        docker_target_id=uuid.uuid4(),
        rule_id=uuid.uuid4(),
        file_path="Dockerfile",
        fingerprint="abc123",
        severity=Severity.high,
        category=Category.security,
        message=message,
    )


def _enrichment(evidence: str, recommendation: str) -> DockerBuildEnrichment:
    return DockerBuildEnrichment(
        repo_id=uuid.uuid4(),
        telemetry_id=uuid.uuid4(),
        rule_slug="container_unbounded_memory",
        evidence=evidence,
        recommendation=recommendation,
    )


def test_prompt_without_runtime_findings_has_no_measured_section() -> None:
    _, user = build_docker_fix_prompt(
        file_path="Dockerfile",
        file_content="FROM python:3.11\n",
        findings=[_finding("runs as root")],
    )
    assert "Measured runtime facts" not in user
    assert "runs as root" in user


def test_measured_facts_carry_their_numbers_into_the_prompt() -> None:
    _, user = build_docker_fix_prompt(
        file_path="compose.yml",
        file_content="services:\n  api:\n    image: x\n",
        findings=[],
        kind="compose",
        runtime_findings=[
            _enrichment(
                "container 'api' peaked at 420 MB with no memory limit set",
                "Set a memory limit around 630 MB.",
            )
        ],
    )
    assert "Measured runtime facts" in user
    assert "peaked at 420 MB" in user
    assert "630 MB" in user
    assert "container_unbounded_memory" in user


def test_runtime_findings_can_stand_alone() -> None:
    # A measurement is actionable with no static rule having fired — that is
    # the whole reason runtime telemetry can produce a fix at all. The findings
    # section must still say something rather than being blank.
    _, user = build_docker_fix_prompt(
        file_path="Dockerfile",
        file_content="FROM python:3.11\n",
        findings=[],
        runtime_findings=[_enrichment("peaked at 420 MB", "Set a limit.")],
    )
    assert NO_STATIC_FINDINGS_PLACEHOLDER in user


def test_static_and_measured_findings_stay_in_separate_sections() -> None:
    # A static finding says the file is wrong; a measurement says what the
    # container did. Collapsing them invites the model to edit away an
    # observation.
    _, user = build_docker_fix_prompt(
        file_path="Dockerfile",
        file_content="FROM python:3.11\n",
        findings=[_finding("runs as root")],
        runtime_findings=[_enrichment("peaked at 420 MB", "Set a limit.")],
    )
    findings_at = user.index("**Findings to fix:**")
    measured_at = user.index("**Measured runtime facts**")
    assert findings_at < measured_at
    assert "runs as root" in user[findings_at:measured_at]


def test_system_prompt_tells_the_model_to_trust_the_measurements() -> None:
    system, _ = build_docker_fix_prompt(
        file_path="Dockerfile",
        file_content="FROM python:3.11\n",
        findings=[],
        runtime_findings=[_enrichment("peaked at 420 MB", "Set a limit.")],
    )
    assert "measured runtime facts" in system.lower()
