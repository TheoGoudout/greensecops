import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.opa.evaluator import (
    POLICY_PACKAGES,
    _discover_policy_packages,
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
        "world_writable_artifact",
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
