import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.opa.evaluator import (
    IAC_TERRAFORM_POLICY_PACKAGES,
    POLICY_PACKAGES,
    OpaUnavailableError,
    WorkflowParseError,
    _discover_policy_packages,
    evaluate_terraform,
    evaluate_workflow,
    parse_workflow_yaml,
)


def test_all_seeded_rules_are_evaluated() -> None:
    """Every Rego rule shipped in app/rules must be an evaluated policy.

    Guards against seeded rules silently never firing (the pre-fix state where
    only 8 of 26 packages — and 2 of 6 security rules — were evaluated).
    """
    packages = _discover_policy_packages()
    assert len(packages) == 26
    # The security rules that were previously unwired must now be evaluated.
    for slug in (
        "hardcoded_secrets",
        "untrusted_actions",
        "oidc_not_used",
        "public_artifact_exposure",
    ):
        assert f"greensecops/security/{slug}" in packages
    assert set(POLICY_PACKAGES) == set(packages)


_SIMPLE_WORKFLOW = """
name: CI
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@main
"""


def _fake_response(json_data: Any, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


def _mock_client(per_package: dict[str, Any]) -> MagicMock:
    """Return a mock AsyncClient whose post() dispatches by URL path."""

    async def _post(url: str, **_kwargs: Any) -> MagicMock:
        for pkg, data in per_package.items():
            if pkg in url:
                return _fake_response(data)
        return _fake_response({})  # undefined — no "result" key

    client = AsyncMock()
    client.post = _post
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def test_parse_valid_yaml() -> None:
    yaml_content = """
name: CI
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
"""
    result = parse_workflow_yaml(yaml_content)
    assert result is not None
    assert result["name"] == "CI"
    assert "build" in result["jobs"]


def test_parse_invalid_yaml_returns_none() -> None:
    result = parse_workflow_yaml("{ invalid: yaml: content: [}")
    assert result is None


def test_parse_non_dict_yaml_returns_none() -> None:
    result = parse_workflow_yaml("- item1\n- item2")
    assert result is None


def test_parse_empty_workflow() -> None:
    result = parse_workflow_yaml("")
    assert result is None


def test_parse_on_key_is_not_coerced_to_boolean() -> None:
    """Regression: the bare ``on:`` key must stay the string "on".

    PyYAML's ``safe_load`` follows YAML 1.1 and coerces ``on`` to the boolean
    ``True``, so the JSON sent to OPA had a ``true`` key and ``input.on`` in the
    Rego rules never matched a real workflow — silently disabling
    pr_target_injection (critical) and missing_concurrency. ruamel.yaml uses the
    YAML 1.2 core schema and keeps it a string.
    """
    result = parse_workflow_yaml(
        "name: CI\n"
        "on:\n"
        "  pull_request_target:\n"
        "jobs:\n"
        "  build:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: echo hi\n"
    )
    assert result is not None
    assert "on" in result
    assert True not in result
    assert isinstance(result["on"], dict)
    assert "pull_request_target" in result["on"]


def test_evaluate_workflow_returns_violations_when_policy_matches() -> None:
    violation = {
        "rule": "unpinned_actions",
        "severity": "high",
        "category": "reliability",
        "job": "build",
        "message": "Step uses mutable ref",
        "context": "actions/checkout@main",
    }
    mock_cm = _mock_client(
        {"reliability/unpinned_actions": {"result": {"violations": [violation]}}}
    )
    with patch("app.services.opa.evaluator.httpx.AsyncClient", return_value=mock_cm):
        violations = asyncio.run(evaluate_workflow(_SIMPLE_WORKFLOW))

    assert len(violations) == 1
    assert violations[0].rule_slug == "unpinned_actions"
    assert violations[0].severity == "high"


def test_evaluate_workflow_returns_empty_when_no_violations() -> None:
    mock_cm = _mock_client({pkg: {"result": {}} for pkg in POLICY_PACKAGES})
    with patch("app.services.opa.evaluator.httpx.AsyncClient", return_value=mock_cm):
        violations = asyncio.run(evaluate_workflow(_SIMPLE_WORKFLOW))

    assert violations == []


def test_evaluate_workflow_logs_error_when_policy_undefined(caplog: Any) -> None:
    # OPA returns {} (no "result" key) → policy not loaded
    mock_cm = _mock_client({})
    with patch("app.services.opa.evaluator.httpx.AsyncClient", return_value=mock_cm):
        import logging

        with caplog.at_level(logging.ERROR, logger="app.services.opa.evaluator"):
            violations = asyncio.run(evaluate_workflow(_SIMPLE_WORKFLOW))

    assert violations == []
    assert any("undefined" in rec.message for rec in caplog.records)


def test_evaluate_workflow_raises_on_unparseable_yaml() -> None:
    # Broken YAML must not silently produce a perfect score
    with pytest.raises(WorkflowParseError):
        asyncio.run(evaluate_workflow("{ invalid: yaml: content: [}"))


def test_evaluate_workflow_raises_when_opa_unreachable() -> None:
    # A connection failure must surface, not be swallowed into zero violations
    async def _post(url: str, **_kwargs: Any) -> MagicMock:
        raise httpx.ConnectError("connection refused")

    client = AsyncMock()
    client.post = _post
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.services.opa.evaluator.httpx.AsyncClient", return_value=cm),
        pytest.raises(OpaUnavailableError),
    ):
        asyncio.run(evaluate_workflow(_SIMPLE_WORKFLOW))


def test_discover_policy_packages_excludes_test_files() -> None:
    packages = _discover_policy_packages()
    assert not any(pkg.endswith("_test") for pkg in packages)


# ─── Terraform ────────────────────────────────────────────────────────────────


def test_all_seeded_terraform_rules_are_evaluated() -> None:
    packages = _discover_policy_packages("iac_terraform")
    assert len(packages) == 8
    for slug in (
        "s3_bucket_public_acl",
        "open_ingress_security_group",
        "unencrypted_ebs_volume",
        "rds_not_encrypted",
        "hardcoded_credentials_in_tf",
    ):
        assert f"greensecops/iac_terraform/security/{slug}" in packages
    assert "greensecops/iac_terraform/reliability/s3_bucket_missing_versioning" in (
        packages
    )
    for slug in ("resource_missing_tags", "variable_missing_description"):
        assert f"greensecops/iac_terraform/maintainability/{slug}" in packages
    assert set(IAC_TERRAFORM_POLICY_PACKAGES) == set(packages)


def test_discover_policy_packages_scopes_domains_independently() -> None:
    # Workflow discovery must not pick up the iac_terraform tree, and vice
    # versa — they're different domains evaluated by different engines.
    workflow_packages = _discover_policy_packages()
    terraform_packages = _discover_policy_packages("iac_terraform")
    assert not any(
        p.startswith("greensecops/iac_terraform/") for p in workflow_packages
    )
    assert all(p.startswith("greensecops/iac_terraform/") for p in terraform_packages)


def test_evaluate_terraform_returns_violations_when_policy_matches() -> None:
    violation = {
        "rule": "s3_bucket_public_acl",
        "severity": "high",
        "category": "security",
        "resource_address": "aws_s3_bucket.data",
        "file_path": "main.tf",
        "message": "Bucket is public",
    }
    mock_cm = _mock_client(
        {
            "iac_terraform/security/s3_bucket_public_acl": {
                "result": {"violations": [violation]}
            }
        }
    )
    with patch("app.services.opa.evaluator.httpx.AsyncClient", return_value=mock_cm):
        violations = asyncio.run(evaluate_terraform({"resource": []}))

    assert len(violations) == 1
    assert violations[0].rule_slug == "s3_bucket_public_acl"
    assert violations[0].resource_address == "aws_s3_bucket.data"
    assert violations[0].file_path == "main.tf"


def test_evaluate_terraform_returns_empty_when_no_violations() -> None:
    mock_cm = _mock_client(
        {pkg: {"result": {}} for pkg in IAC_TERRAFORM_POLICY_PACKAGES}
    )
    with patch("app.services.opa.evaluator.httpx.AsyncClient", return_value=mock_cm):
        violations = asyncio.run(evaluate_terraform({"resource": []}))

    assert violations == []


def test_evaluate_terraform_raises_when_opa_unreachable() -> None:
    async def _post(url: str, **_kwargs: Any) -> MagicMock:
        raise httpx.ConnectError("connection refused")

    client = AsyncMock()
    client.post = _post
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.services.opa.evaluator.httpx.AsyncClient", return_value=cm),
        pytest.raises(OpaUnavailableError),
    ):
        asyncio.run(evaluate_terraform({"resource": []}))
