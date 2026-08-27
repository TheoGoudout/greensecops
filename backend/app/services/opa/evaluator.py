import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

import httpx

from app.core.config import settings
from app.core.rego_metadata import (
    PACKAGES_BINDING,
    VIOLATIONS_BINDING,
    domain_packages_expr,
    domain_violations_expr,
)
from app.services.workflow_enrichment import attach_action_metadata

# Re-exported: parsing moved out so scripts/validate_examples.py can share it
# without pulling in httpx, but evaluate_workflow's callers still import it here.
from app.services.workflow_parser import parse_workflow_yaml as parse_workflow_yaml
from app.services.yaml_positions import END_LINE_KEY, START_LINE_KEY

if TYPE_CHECKING:  # pragma: no cover - typing-only import
    from _typeshed import DataclassInstance

# Any of the per-domain violation dataclasses below.
V = TypeVar("V", bound="DataclassInstance")


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

    Evaluation no longer walks this list — a domain query reaches every package
    OPA has loaded, whether or not this process can see the file. What the list
    still answers is the question it was introduced for: whether a rule that is
    seeded and shown as enabled is one the domain query actually grades against.
    ``tests/services/test_opa_evaluator.py`` asserts exactly that, so a rule
    filed outside ``<domain>/<category>/`` still fails loudly instead of
    silently never firing.

    The package path returned always mirrors the file's location relative to
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
class AnsibleOpaViolation:
    """One `iac_ansible` violation.

    ``task_name`` is both the human locator and what the fingerprint's
    discriminator keys on, which is why the rules emit the task's own ``name:``
    rather than a positional index: a task keeps its name when another is
    inserted above it, so a dismissal survives the edit.
    """

    rule_slug: str
    severity: str
    category: str
    message: str
    file_path: str = ""
    # Empty for a finding about a file rather than a task — a galaxy
    # requirement, or a credential in a variables file.
    task_name: str | None = None
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


# Every domain's rules live under `greensecops.<domain>.<category>.<rule>`, and
# the domain is exactly the directory name under `app/rules/` — the same
# property `RuleDomain(dir_name)` relies on. Naming them here rather than
# inline keeps the string that selects an engine's rules in one place.
DOMAIN_CI_WORKFLOW = "ci_workflow"
DOMAIN_CI_TELEMETRY = "ci_telemetry"
DOMAIN_IAC_TERRAFORM = "iac_terraform"
DOMAIN_IAC_ANSIBLE = "iac_ansible"
DOMAIN_CLOUD_AWS = "cloud_aws"
DOMAIN_CONTAINER_DOCKER = "container_docker"
DOMAIN_CONTAINER_RUNTIME = "container_runtime"

# The packages each domain ships, discovered from the Rego files on disk.
#
# These no longer drive evaluation — a domain query grades whatever OPA has
# loaded, so the backend's own copy of the rules directory is not consulted at
# scan time and the hand-written fallback list that used to guard an absent
# one is gone with it. What they still do is let the catalog be checked against
# the tree: `tests/services/test_opa_evaluator.py` asserts that every shipped
# rule is one the domain query reaches, which is the drift this discovery was
# introduced to catch.
POLICY_PACKAGES = _discover_policy_packages(DOMAIN_CI_WORKFLOW)
IAC_TERRAFORM_POLICY_PACKAGES = _discover_policy_packages(DOMAIN_IAC_TERRAFORM)
IAC_ANSIBLE_POLICY_PACKAGES = _discover_policy_packages(DOMAIN_IAC_ANSIBLE)
CLOUD_AWS_POLICY_PACKAGES = _discover_policy_packages(DOMAIN_CLOUD_AWS)
CI_TELEMETRY_POLICY_PACKAGES = _discover_policy_packages(DOMAIN_CI_TELEMETRY)
CONTAINER_DOCKER_POLICY_PACKAGES = _discover_policy_packages(DOMAIN_CONTAINER_DOCKER)
CONTAINER_RUNTIME_POLICY_PACKAGES = _discover_policy_packages(DOMAIN_CONTAINER_RUNTIME)


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


async def _evaluate_domain(parsed: dict[str, Any], domain: str) -> list[dict[str, Any]]:
    """Evaluate one domain's whole rule set in a single call; return raw dicts.

    Shared by every ``evaluate_*`` below — the HTTP/error-handling shape is
    identical, only the input document, the domain, and the dataclass each raw
    violation gets mapped into differ.

    One request per *domain*, not per rule. The previous shape POSTed the whole
    input document once per package, sequentially: 43 round trips to grade a
    cloud snapshot, 61 for a workflow, each re-serializing the same document.
    ``/v1/query`` evaluates every package under the domain in one pass, so the
    cost stops scaling with the size of the rule catalog.

    Two details of that endpoint shape this function, and both are ways a
    refactor here reports a perfect score instead of a failure:

    * It answers with variable *bindings*, not values. The comprehension has to
      be bound; submitted bare it returns ``{"result": [{}]}``, which is a
      successful response carrying no violations.
    * A domain whose policies are not loaded answers *identically* to a
      spotless document. So the query also asks which packages OPA has for the
      domain, and an empty inventory is treated as the outage it is.
    """
    query = (
        f"{VIOLATIONS_BINDING} = {domain_violations_expr(domain)}; "
        f"{PACKAGES_BINDING} = {domain_packages_expr(domain)}"
    )
    url = f"{settings.OPA_URL}/v1/query"
    # One request now carries what 61 shared before, so it is given longer
    # than the old per-package 10s — while the worst case for a whole
    # domain drops from 61 timeouts to one.
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(url, json={"query": query, "input": parsed})
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            # A perfect score must not be reported just because OPA is down:
            # surface the outage so the analysis is marked failed.
            raise OpaUnavailableError(
                f"OPA evaluation failed for {domain}: {exc}"
            ) from exc

    bindings = data.get("result") or []
    if not bindings:
        # An undefined query — every binding failed to resolve. Nothing was
        # graded, so nothing can be concluded about the document.
        raise OpaUnavailableError(
            f"OPA returned no bindings for {domain} — the query did not resolve"
        )

    raw_violations: list[dict[str, Any]] = []
    loaded_packages = 0
    for binding in bindings:
        raw_violations.extend(binding.get(VIOLATIONS_BINDING, []))
        loaded_packages += len(binding.get(PACKAGES_BINDING, []))

    if not loaded_packages:
        raise OpaUnavailableError(
            f"OPA has no policies loaded for {domain} — the document was not "
            "graded against any rule"
        )
    return raw_violations


# A rego rule emits a flat object whose keys match the violation dataclasses'
# field names one-for-one, with one exception: the slug is called ``rule``.
_SLUG_KEY = "rule"


def _violation(cls: type[V], raw: dict[str, Any], default_category: str) -> V:
    """Build one violation dataclass from a raw OPA result object.

    Field-name driven rather than hand-mapped, so a dataclass gaining a new
    optional locator (a Compose ``service_name``, a cloud ``region``) needs no
    change here. Anything the rule omitted falls back to the field's own
    default; a required field the rule left out becomes ``""`` rather than
    raising, because one malformed rule must not fail the whole evaluation.

    ``default_category`` is per-domain: a rule that omits its category is
    almost always in that engine's dominant one.
    """
    values: dict[str, Any] = {}
    for field in dataclasses.fields(cls):
        if field.name == "rule_slug":
            values[field.name] = raw.get(_SLUG_KEY, "unknown")
        elif field.name == "category":
            values[field.name] = raw.get("category", default_category)
        elif field.name == "severity":
            values[field.name] = raw.get("severity", "medium")
        elif field.name in raw:
            values[field.name] = raw[field.name]
        elif (
            field.default is dataclasses.MISSING
            and field.default_factory is dataclasses.MISSING
        ):
            values[field.name] = ""
    return cls(**values)


async def _evaluate(
    payload: dict[str, Any],
    domain: str,
    cls: type[V],
    default_category: str,
) -> list[V]:
    """Evaluate ``payload`` against ``domain``'s rules and map results to ``cls``."""
    raw = await _evaluate_domain(payload, domain)
    return [_violation(cls, v, default_category) for v in raw]


async def evaluate_workflow(
    raw_content: str,
    *,
    action_metadata: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[OpaViolation]:
    """Evaluate one workflow, optionally enriched with GitHub action facts.

    ``action_metadata`` carries what the API knows about each ``uses:`` — see
    ``services/github/action_metadata.py``. It is an optional keyword so this
    function stays pure and offline-testable: omitted, the ``__actions__`` key
    is absent, and the four rules that read it are silent by construction. The
    collection itself is async and cached, and belongs to the caller.
    """
    parsed = parse_workflow_yaml(raw_content)
    if parsed is None:
        raise WorkflowParseError("Workflow file is not a valid YAML mapping")
    attach_action_metadata(parsed, action_metadata)

    violations = await _evaluate(
        parsed, DOMAIN_CI_WORKFLOW, OpaViolation, "reliability"
    )
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
    return await _evaluate(
        parsed_config, DOMAIN_IAC_TERRAFORM, TerraformOpaViolation, "security"
    )


async def evaluate_ansible(
    document: dict[str, Any],
) -> list[AnsibleOpaViolation]:
    """Evaluate a project's Ansible files against the `iac_ansible` rules.

    The document is an **envelope** — ``{"files": [...]}``, one entry per
    playbook, task file, variables file or galaxy requirements file — rather
    than the single merged config Terraform and Docker send. A task file is not
    mergeable with a playbook, and the envelope is also what keeps the suite
    silent on foreign input: every Ansible rule opens by iterating
    ``input.files``, so a document without that key trips nothing. See
    ``services/ansible/parser.merge_ansible_files``.

    Defaults to ``reliability`` for a rule that names no category, matching what
    most of the corpus grades.
    """
    return await _evaluate(
        document, DOMAIN_IAC_ANSIBLE, AnsibleOpaViolation, "reliability"
    )


async def evaluate_docker(
    merged_document: dict[str, Any],
) -> list[DockerOpaViolation]:
    """Evaluate a target's merged Dockerfile/Compose document against rules.

    Like ``evaluate_terraform``, parsing happens upstream (see
    ``services/docker/merge.merge_docker_files``) — a target is many files
    folded into one document so rules can correlate a Compose service with the
    Dockerfile it builds, which a per-file call could not do.
    """
    return await _evaluate(
        merged_document,
        DOMAIN_CONTAINER_DOCKER,
        DockerOpaViolation,
        "security",
    )


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
    return await _evaluate(
        telemetry,
        DOMAIN_CONTAINER_RUNTIME,
        CiTelemetryOpaViolation,
        "energy",
    )


async def evaluate_ci_telemetry(
    telemetry: dict[str, Any],
) -> list[CiTelemetryOpaViolation]:
    """Evaluate a completed telemetry run's runner_specs/metrics.

    ``telemetry`` is ``{"runner_specs": {...}, "metrics": {...}}`` — the same
    two JSON blobs ``TelemetryRun`` stores, decoded. Dynamic (runtime)
    counterpart of ``evaluate_workflow``'s static YAML analysis: same engine,
    same rule-authoring model, different signal.
    """
    return await _evaluate(
        telemetry, DOMAIN_CI_TELEMETRY, CiTelemetryOpaViolation, "reliability"
    )


async def evaluate_cloud(resources: dict[str, Any]) -> list[CloudOpaViolation]:
    """Evaluate a normalized AWS resource snapshot against cloud posture rules.

    ``resources`` is the dict built by
    ``services/cloud/aws_collector.collect_account_resources`` — already
    normalized/merged across regions, mirroring how ``evaluate_terraform``
    takes an already-merged root config rather than raw files.
    """
    return await _evaluate(resources, DOMAIN_CLOUD_AWS, CloudOpaViolation, "security")
