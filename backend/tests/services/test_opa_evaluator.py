import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.opa.evaluator import (
    POLICY_PACKAGES,
    OpaUnavailableError,
    WorkflowParseError,
    discover_policy_packages,
    evaluate_workflow,
    parse_workflow_yaml,
)

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


def test_discover_policy_packages_covers_all_rules() -> None:
    packages = discover_policy_packages()
    # Every rego rule shipped in app/rules must be evaluated — including ones
    # that used to be missing from the old hardcoded list.
    assert "greensecops/security/hardcoded_secrets" in packages
    assert "greensecops/reliability/unpinned_actions" in packages
    assert len(packages) >= 25
    # Test files are not policies
    assert not any(pkg.endswith("_test") for pkg in packages)
    assert POLICY_PACKAGES == packages
