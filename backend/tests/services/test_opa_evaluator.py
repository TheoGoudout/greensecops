from app.services.opa.evaluator import parse_workflow_yaml


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
