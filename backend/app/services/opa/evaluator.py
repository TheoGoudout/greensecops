import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings

# Re-exported: parsing moved out so scripts/validate_examples.py can share it
# without pulling in httpx, but evaluate_workflow's callers still import it here.
from app.services.workflow_parser import parse_workflow_yaml as parse_workflow_yaml
from app.services.yaml_positions import END_LINE_KEY, START_LINE_KEY

logger = logging.getLogger(__name__)


class WorkflowParseError(Exception):
    """Raised when a workflow file is not a parseable YAML mapping."""


class OpaUnavailableError(Exception):
    """Raised when the OPA service cannot be reached or returns an error."""


# Every analysis domain gets its own named directory:
# app/rules/<domain_dir>/<category>/<name>.rego (e.g.
# app/rules/iac_terraform/security/s3_public_bucket.rego). Every file
# declares package greensecops.<domain_dir>.<category>.<name> exposing
# `violations`.
_RULES_DIR = Path(__file__).resolve().parents[2] / "rules"


def _discover_policy_packages(domain_dir: str) -> list[str]:
    """Enumerate OPA package paths from one domain's shipped Rego rule files.

    Deriving this from the filesystem (rather than a hand-maintained list)
    guarantees that every rule which is seeded and shown as enabled is also
    actually evaluated — the two can no longer silently drift apart. The
    package path returned always mirrors the file's location relative to
    ``_RULES_DIR``, so it matches that file's own ``package`` declaration.
    """
    search_root = _RULES_DIR / domain_dir
    if not search_root.is_dir():
        return []
    packages = sorted(
        f"greensecops/{rego.relative_to(_RULES_DIR).with_suffix('').as_posix()}"
        for rego in search_root.glob("*/*.rego")
        if not rego.name.endswith("_test.rego")
    )
    return packages


@dataclass
class OpaViolation:
    rule_slug: str
    severity: str
    category: str
    message: str
    job: str | None = None
    step: str | None = None
    step_index: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    context: str | None = None
    discriminator: str | None = None


@dataclass
class TerraformOpaViolation:
    rule_slug: str
    severity: str
    category: str
    message: str
    resource_address: str | None = None
    file_path: str = ""
    line_start: int | None = None
    line_end: int | None = None
    context: str | None = None
    discriminator: str | None = None


@dataclass
class DockerOpaViolation:
    rule_slug: str
    severity: str
    category: str
    message: str
    file_path: str = ""
    # Whichever of the two applies to the rule: a Compose rule names the
    # service it fired on, a Dockerfile rule the build stage. Both nullable —
    # a file-level rule (e.g. a missing OCI label) names neither.
    service_name: str | None = None
    stage_name: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    context: str | None = None
    discriminator: str | None = None


@dataclass
class CloudOpaViolation:
    rule_slug: str
    severity: str
    category: str
    message: str
    resource_type: str = ""
    resource_id: str = ""
    region: str | None = None
    context: str | None = None
    discriminator: str | None = None


@dataclass
class CiTelemetryOpaViolation:
    rule_slug: str
    severity: str
    category: str
    # DynamicEnrichment persists evidence/recommendation rather than a single
    # message (see its docstring: deliberately thinner than the other
    # domains' findings — no severity/category/status persisted either), so
    # this dataclass mirrors that shape instead of message/context.
    evidence: str
    recommendation: str


# All registered policy packages to evaluate against, discovered from the
# shipped Rego rule files so no rule is left unevaluated. Falls back to the
# core set if the rules directory is unavailable at runtime.
POLICY_PACKAGES = _discover_policy_packages("ci_workflow") or [
    "greensecops/ci_workflow/energy/caching_missing",
    "greensecops/ci_workflow/energy/runner_sizing",
    "greensecops/ci_workflow/reliability/missing_timeout",
    "greensecops/ci_workflow/reliability/unpinned_actions",
    "greensecops/ci_workflow/security/excessive_token_permissions",
    "greensecops/ci_workflow/security/pr_target_injection",
    "greensecops/ci_workflow/performance/unnecessary_full_checkout",
    "greensecops/ci_workflow/maintainability/missing_workflow_description",
]

IAC_TERRAFORM_POLICY_PACKAGES = _discover_policy_packages("iac_terraform")
CLOUD_AWS_POLICY_PACKAGES = _discover_policy_packages("cloud_aws")
CI_TELEMETRY_POLICY_PACKAGES = _discover_policy_packages("ci_telemetry")
CONTAINER_DOCKER_POLICY_PACKAGES = _discover_policy_packages("container_docker")
CONTAINER_RUNTIME_POLICY_PACKAGES = _discover_policy_packages("container_runtime")


def _attach_positions(violation: OpaViolation, parsed: dict[str, Any]) -> None:
    """Fill in a violation's line span from the parsed document.

    Replaces a second, post-evaluation parse that resolved a line only when
    the violation named a job and matched its step by ``uses`` — so every
    finding on a ``run:`` step had no line at all, and two steps sharing an
    action both reported the first one's line. Keyed on ``step_index``, which
    every per-step rule already emits, it is exact for both.

    A rule that reports its own span wins: it knows which part of the step is
    at fault, where this only knows the step.
    """
    if violation.line_start is not None:
        return
    jobs = parsed.get("jobs")
    if violation.job is None or not isinstance(jobs, dict):
        return
    node: Any = jobs.get(violation.job)
    if not isinstance(node, dict):
        return

    if violation.step_index is not None:
        steps = node.get("steps")
        if isinstance(steps, list) and 0 <= violation.step_index < len(steps):
            step = steps[violation.step_index]
            if isinstance(step, dict):
                node = step

    violation.line_start = node.get(START_LINE_KEY)
    violation.line_end = node.get(END_LINE_KEY)


async def _evaluate_packages(
    parsed: dict[str, Any], package_paths: list[str]
) -> list[dict[str, Any]]:
    """POST ``parsed`` as OPA input to each package; return raw violation dicts.

    Shared by :func:`evaluate_workflow` and :func:`evaluate_terraform` — the
    HTTP/error-handling shape is identical, only the input document, package
    list, and the dataclass each raw violation gets mapped into differ.
    """
    raw_violations: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        for package_path in package_paths:
            url = f"{settings.OPA_URL}/v1/data/{package_path}"
            try:
                response = await client.post(url, json={"input": parsed})
                if response.status_code == 404:
                    # Policy not loaded yet — skip silently
                    continue
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPError as exc:
                # A perfect score must not be reported just because OPA is
                # down: surface the outage so the analysis is marked failed.
                raise OpaUnavailableError(
                    f"OPA evaluation failed for {package_path}: {exc}"
                ) from exc
            if "result" not in data:
                logger.error(
                    "OPA package %s is undefined — policy not loaded in OPA",
                    package_path,
                )
                continue
            raw_violations.extend(data["result"].get("violations", []))
    return raw_violations


async def evaluate_workflow(raw_content: str) -> list[OpaViolation]:
    parsed = parse_workflow_yaml(raw_content)
    if parsed is None:
        raise WorkflowParseError("Workflow file is not a valid YAML mapping")

    raw_violations = await _evaluate_packages(parsed, POLICY_PACKAGES)
    violations = [
        OpaViolation(
            rule_slug=v.get("rule", "unknown"),
            severity=v.get("severity", "medium"),
            category=v.get("category", "reliability"),
            message=v.get("message", ""),
            job=v.get("job"),
            step=v.get("step"),
            step_index=v.get("step_index"),
            line_start=v.get("line_start"),
            line_end=v.get("line_end"),
            context=v.get("context"),
            discriminator=v.get("discriminator"),
        )
        for v in raw_violations
    ]
    # Attribution lives here, where the parsed document already is, rather
    # than in the analysis task — which had to re-parse the same bytes.
    for violation in violations:
        _attach_positions(violation, parsed)
    return violations


async def evaluate_terraform(
    parsed_config: dict[str, Any],
) -> list[TerraformOpaViolation]:
    """Evaluate an already-merged Terraform root config against IaC rules.

    Unlike ``evaluate_workflow``, parsing happens upstream (see
    ``services/terraform/hcl_parser.py``) since a Terraform root is multiple
    files merged into one logical document before evaluation, not a single
    raw string.
    """
    raw_violations = await _evaluate_packages(
        parsed_config, IAC_TERRAFORM_POLICY_PACKAGES
    )
    return [
        TerraformOpaViolation(
            rule_slug=v.get("rule", "unknown"),
            severity=v.get("severity", "medium"),
            category=v.get("category", "security"),
            message=v.get("message", ""),
            resource_address=v.get("resource_address"),
            file_path=v.get("file_path", ""),
            line_start=v.get("line_start"),
            line_end=v.get("line_end"),
            context=v.get("context"),
            discriminator=v.get("discriminator"),
        )
        for v in raw_violations
    ]


async def evaluate_docker(
    merged_document: dict[str, Any],
) -> list[DockerOpaViolation]:
    """Evaluate a target's merged Dockerfile/Compose document against rules.

    Like ``evaluate_terraform``, parsing happens upstream (see
    ``services/docker/merge.merge_docker_files``) — a target is many files
    folded into one document so rules can correlate a Compose service with the
    Dockerfile it builds, which a per-file call could not do.
    """
    raw_violations = await _evaluate_packages(
        merged_document, CONTAINER_DOCKER_POLICY_PACKAGES
    )
    return [
        DockerOpaViolation(
            rule_slug=v.get("rule", "unknown"),
            severity=v.get("severity", "medium"),
            category=v.get("category", "security"),
            message=v.get("message", ""),
            file_path=v.get("file_path", ""),
            service_name=v.get("service_name"),
            stage_name=v.get("stage_name"),
            line_start=v.get("line_start"),
            line_end=v.get("line_end"),
            context=v.get("context"),
            discriminator=v.get("discriminator"),
        )
        for v in raw_violations
    ]


async def evaluate_container_runtime(
    telemetry: dict[str, Any],
) -> list[CiTelemetryOpaViolation]:
    """Evaluate a Docker build/runtime telemetry payload.

    Dynamic counterpart of ``evaluate_docker``: same engine and rule-authoring
    model, measured input instead of source. Reuses
    ``CiTelemetryOpaViolation`` rather than introducing a near-identical
    dataclass — both dynamic domains persist evidence/recommendation rather
    than message/context, so the shape is genuinely the same one.
    """
    raw_violations = await _evaluate_packages(
        telemetry, CONTAINER_RUNTIME_POLICY_PACKAGES
    )
    return [
        CiTelemetryOpaViolation(
            rule_slug=v.get("rule", "unknown"),
            severity=v.get("severity", "medium"),
            category=v.get("category", "energy"),
            evidence=v.get("evidence", ""),
            recommendation=v.get("recommendation", ""),
        )
        for v in raw_violations
    ]


async def evaluate_ci_telemetry(
    telemetry: dict[str, Any],
) -> list[CiTelemetryOpaViolation]:
    """Evaluate a completed telemetry run's runner_specs/metrics.

    ``telemetry`` is ``{"runner_specs": {...}, "metrics": {...}}`` — the same
    two JSON blobs ``TelemetryRun`` stores, decoded. Dynamic (runtime)
    counterpart of ``evaluate_workflow``'s static YAML analysis: same engine,
    same rule-authoring model, different signal.
    """
    raw_violations = await _evaluate_packages(telemetry, CI_TELEMETRY_POLICY_PACKAGES)
    return [
        CiTelemetryOpaViolation(
            rule_slug=v.get("rule", "unknown"),
            severity=v.get("severity", "medium"),
            category=v.get("category", "reliability"),
            evidence=v.get("evidence", ""),
            recommendation=v.get("recommendation", ""),
        )
        for v in raw_violations
    ]


async def evaluate_cloud(resources: dict[str, Any]) -> list[CloudOpaViolation]:
    """Evaluate a normalized AWS resource snapshot against cloud posture rules.

    ``resources`` is the dict built by
    ``services/cloud/aws_collector.collect_account_resources`` — already
    normalized/merged across regions, mirroring how ``evaluate_terraform``
    takes an already-merged root config rather than raw files.
    """
    raw_violations = await _evaluate_packages(resources, CLOUD_AWS_POLICY_PACKAGES)
    return [
        CloudOpaViolation(
            rule_slug=v.get("rule", "unknown"),
            severity=v.get("severity", "medium"),
            category=v.get("category", "security"),
            message=v.get("message", ""),
            resource_type=v.get("resource_type", ""),
            resource_id=v.get("resource_id", ""),
            region=v.get("region"),
            context=v.get("context"),
            discriminator=v.get("discriminator"),
        )
        for v in raw_violations
    ]
