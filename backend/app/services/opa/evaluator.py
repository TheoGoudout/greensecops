import logging
from dataclasses import dataclass, field
from typing import Any

import httpx
import yaml

from app.core.config import settings

logger = logging.getLogger(__name__)


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


# All registered policy packages to evaluate against
POLICY_PACKAGES = [
    "greensecops/energy/caching_missing",
    "greensecops/energy/runner_sizing",
    "greensecops/reliability/missing_timeout",
    "greensecops/reliability/unpinned_actions",
    "greensecops/security/excessive_token_permissions",
    "greensecops/security/pr_target_injection",
    "greensecops/performance/unnecessary_full_checkout",
    "greensecops/maintainability/missing_workflow_description",
]


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
        return []

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
                result = response.json().get("result", {})
                raw_violations: list[dict[str, Any]] = result.get("violations", [])
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
            except httpx.HTTPError as exc:
                logger.warning("OPA evaluation failed for %s: %s", package_path, exc)

    return violations
