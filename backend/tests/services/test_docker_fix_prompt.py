"""Tests for the Docker fix prompt, in particular the measured-facts block."""

import uuid

from app.models import DockerBuildEnrichment, DockerFinding
from app.models.enums import Category, Severity
from app.services.llm.docker_fix_prompt import (
    NO_STATIC_FINDINGS_PLACEHOLDER,
    RepositoryFacts,
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


# ─── Repository facts (OCI annotations) ──────────────────────────────────────


def test_prompt_without_a_repository_has_no_repository_section() -> None:
    """A caller that cannot resolve the repository tells the model nothing.

    Nothing is the safe state: the alternative is a label pointing somewhere
    else, which tooling believes.
    """
    _, user = build_docker_fix_prompt(
        file_path="Dockerfile",
        file_content="FROM python:3.11\n",
        findings=[_finding("no OCI source label")],
    )
    assert "**Repository**" not in user


def test_repository_facts_give_the_annotations_a_real_url() -> None:
    """The label has to name *this* repository.

    With no repository in the prompt the model reached for the URL in the
    rule's own example, so every fixed image claimed to come from
    `github.com/example/app`.
    """
    _, user = build_docker_fix_prompt(
        file_path="Dockerfile",
        file_content="FROM python:3.11\n",
        findings=[_finding("no OCI source label")],
        repository=RepositoryFacts.from_full_name("acme/web-app"),
    )
    assert "https://github.com/acme/web-app" in user
    # The image title is the repository's own name, not the owner-qualified one.
    assert "`org.opencontainers.image.title`: web-app" in user


def test_repository_facts_derive_the_url_from_the_full_name() -> None:
    facts = RepositoryFacts.from_full_name("acme/web-app")
    assert facts.url == "https://github.com/acme/web-app"
    assert facts.image_title == "web-app"


def test_system_prompt_forbids_placeholder_annotations() -> None:
    system, _ = build_docker_fix_prompt(
        file_path="Dockerfile",
        file_content="FROM python:3.11\n",
        findings=[_finding("no OCI source label")],
    )
    assert "Never write an example or placeholder URL" in system
    # A revision baked in as a literal is wrong on every later build.
    assert "org.opencontainers.image.revision" in system


def test_repository_and_measured_sections_coexist() -> None:
    _, user = build_docker_fix_prompt(
        file_path="Dockerfile",
        file_content="FROM python:3.11\n",
        findings=[_finding("no OCI source label")],
        runtime_findings=[_enrichment("peaked at 420 MB", "set a memory limit")],
        repository=RepositoryFacts.from_full_name("acme/web-app"),
    )
    assert user.index("**Repository**") < user.index("**Measured runtime facts**")
    assert "peaked at 420 MB" in user
    assert "https://github.com/acme/web-app" in user


# ─── Verified base image digests ─────────────────────────────────────────────


def test_prompt_without_digests_has_no_digest_section() -> None:
    _, user = build_docker_fix_prompt(
        file_path="Dockerfile",
        file_content="FROM python:3.11\n",
        findings=[_finding("base image is not pinned")],
    )
    assert "Verified base image digests" not in user


def test_verified_digests_are_offered_with_the_tag_kept() -> None:
    """The rule wants `image:tag@sha256:...`, so the prompt shows that shape.

    Without any digest to offer, the system prompt's honest instruction was
    "leave it and report it unfixable" — which meant `unpinned_base_image` was
    effectively never auto-fixed.
    """
    digest = "sha256:" + "cd" * 32
    _, user = build_docker_fix_prompt(
        file_path="Dockerfile",
        file_content="FROM python:3.12-slim\n",
        findings=[_finding("base image is not pinned")],
        base_image_digests={"python:3.12-slim": digest},
    )
    assert "Verified base image digests" in user
    assert f"python:3.12-slim@{digest}" in user


def test_system_prompt_allows_only_the_listed_digests() -> None:
    system, _ = build_docker_fix_prompt(
        file_path="Dockerfile",
        file_content="FROM python:3.11\n",
        findings=[_finding("base image is not pinned")],
    )
    assert "Verified base image digests" in system
    assert "do NOT invent or guess a digest" in system
