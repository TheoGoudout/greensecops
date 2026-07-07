"""Unit tests for fix_generation helpers."""

from types import SimpleNamespace

from app.models import LLMProvider
from app.workers.tasks.fix_generation import _resolve_llm_provider, _validate_patch

_WORKFLOW = (
    "name: CI\n"
    "on: push\n"
    "jobs:\n"
    "  build:\n"
    "    runs-on: ubuntu-latest\n"
    "    steps:\n"
    "      - uses: actions/checkout@v4\n"
)


def test_validate_patch_rejects_missing_patch() -> None:
    error = _validate_patch(_WORKFLOW, None)
    assert error is not None
    assert "no patch" in error


def test_validate_patch_rejects_non_applying_patch() -> None:
    patch = "@@ -100,1 +100,1 @@\n-nonexistent line\n+replacement\n"
    error = _validate_patch(_WORKFLOW, patch)
    assert error is not None
    assert "does not apply" in error


def test_validate_patch_rejects_invalid_yaml_result() -> None:
    # Replace the first line with structurally broken YAML
    patch = "@@ -1,1 +1,1 @@\n-name: CI\n+{ invalid: yaml: [}\n"
    error = _validate_patch(_WORKFLOW, patch)
    assert error is not None
    assert "not valid YAML" in error


def test_validate_patch_accepts_good_patch() -> None:
    patch = "@@ -5,1 +5,2 @@\n     runs-on: ubuntu-latest\n+    timeout-minutes: 15\n"
    assert _validate_patch(_WORKFLOW, patch) is None


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
