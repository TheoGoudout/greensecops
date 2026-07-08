"""Unit tests for fix_generation helpers."""

from types import SimpleNamespace

from app.models import LLMProvider
from app.workers.tasks.fix_generation import (
    _is_valid_workflow_yaml,
    _parse_llm_response,
    _resolve_llm_provider,
    restore_trailing_whitespace,
)

_WORKFLOW = (
    "name: CI\n"
    "on: push\n"
    "jobs:\n"
    "  build:\n"
    "    runs-on: ubuntu-latest\n"
    "    steps:\n"
    "      - uses: actions/checkout@v4\n"
)


# ─── _parse_llm_response ─────────────────────────────────────────────────────


def test_parse_llm_response_extracts_full_content() -> None:
    response = f"<full_content>\n{_WORKFLOW}</full_content>"
    assert _parse_llm_response(response) == _WORKFLOW.rstrip("\n")


def test_parse_llm_response_missing_block_returns_empty() -> None:
    assert _parse_llm_response("no delimiters here") == ""


def test_parse_llm_response_ignores_surrounding_prose() -> None:
    response = (
        "Here is the fixed workflow:\n"
        "<full_content>\nname: CI\non: push\n</full_content>\n"
        "All issues addressed."
    )
    assert _parse_llm_response(response) == "name: CI\non: push"


# ─── _is_valid_workflow_yaml ─────────────────────────────────────────────────


def test_valid_workflow_yaml_accepted() -> None:
    assert _is_valid_workflow_yaml(_WORKFLOW) is True


def test_invalid_yaml_rejected() -> None:
    assert _is_valid_workflow_yaml("{ invalid: yaml: [}") is False


def test_non_mapping_yaml_rejected() -> None:
    assert _is_valid_workflow_yaml("- just\n- a\n- list\n") is False


# ─── restore_trailing_whitespace ─────────────────────────────────────────────


def test_restore_trailing_whitespace_restores_stripped_space() -> None:
    original = "hello   \nworld"
    patched = "hello\nworld"
    result = restore_trailing_whitespace(original, patched)
    assert result == "hello   \nworld"


def test_restore_trailing_whitespace_keeps_new_content() -> None:
    # When stripped content differs, keep the new line
    original = "hello\nworld"
    patched = "hello\nuniverse"
    result = restore_trailing_whitespace(original, patched)
    assert result == "hello\nuniverse"


def test_restore_trailing_whitespace_no_change_needed() -> None:
    original = "a\nb\nc"
    patched = "a\nb\nc"
    result = restore_trailing_whitespace(original, patched)
    assert result == "a\nb\nc"


def test_restore_trailing_whitespace_new_lines_beyond_original() -> None:
    # Extra lines in patched that have no corresponding original line are kept as-is
    original = "a"
    patched = "a\nb\nc"
    result = restore_trailing_whitespace(original, patched)
    assert result == "a\nb\nc"


def test_restore_trailing_whitespace_tab_trailing() -> None:
    original = "line\t\nend"
    patched = "line\nend"
    result = restore_trailing_whitespace(original, patched)
    assert result == "line\t\nend"


# ─── _resolve_llm_provider ───────────────────────────────────────────────────


def test_resolve_llm_provider_uses_provider_default_model() -> None:
    # A repo pinned to anthropic without a model must NOT fall back to an
    # OpenAI model name.
    repo = SimpleNamespace(
        llm_provider=LLMProvider.anthropic,
        llm_model=None,
        organization=None,
    )
    provider, model = _resolve_llm_provider(repo)
    assert provider == "anthropic"
    assert "gpt" not in model
