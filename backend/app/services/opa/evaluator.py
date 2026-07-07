import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml

from app.core.config import settings

logger = logging.getLogger(__name__)

# Directory bundling the rego policies shipped with the backend image
# (also copied into the OPA image, see opa/Dockerfile).
RULES_DIR = Path(__file__).resolve().parents[2] / "rules"


class WorkflowParseError(Exception):
    """Raised when a workflow file is not a parseable YAML mapping."""


class OpaUnavailableError(Exception):
    """Raised when the OPA service cannot be reached or returns an error."""


@dataclass
class OpaViolation:
    rule_slug: str
    severity: str
    category: str
    message: str
    job: str | None = None
    step: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    context: str | None = None


def discover_policy_packages() -> list[str]:
    """Discover policy packages by scanning the bundled rego rules.

    Each ``<category>/<name>.rego`` (tests excluded) maps to the OPA package
    ``greensecops/<category>/<name>``, so a newly added rule is evaluated
    without having to be registered in a hardcoded list.
    """
    packages = [
        f"greensecops/{path.parent.name}/{path.stem}"
        for path in sorted(RULES_DIR.glob("*/*.rego"))
        if not path.stem.endswith("_test")
    ]
    if not packages:
        logger.error("No rego rules found under %s", RULES_DIR)
    return packages


POLICY_PACKAGES = discover_policy_packages()


def parse_workflow_yaml(raw_content: str) -> dict[str, Any] | None:
    try:
        parsed = yaml.safe_load(raw_content)
        if not isinstance(parsed, dict):
            return None
        return parsed
    except yaml.YAMLError as exc:
        logger.warning("Failed to parse workflow YAML: %s", exc)
        return None


async def evaluate_workflow(raw_content: str) -> list[OpaViolation]:
    parsed = parse_workflow_yaml(raw_content)
    if parsed is None:
        raise WorkflowParseError("Workflow file is not a valid YAML mapping")

    violations: list[OpaViolation] = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        for package_path in POLICY_PACKAGES:
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
            raw_violations: list[dict[str, Any]] = data["result"].get("violations", [])
            for v in raw_violations:
                violations.append(
                    OpaViolation(
                        rule_slug=v.get("rule", "unknown"),
                        severity=v.get("severity", "medium"),
                        category=v.get("category", "reliability"),
                        message=v.get("message", ""),
                        job=v.get("job"),
                        step=v.get("step"),
                        line_start=v.get("line_start"),
                        line_end=v.get("line_end"),
                        context=v.get("context"),
                    )
                )

    return violations
