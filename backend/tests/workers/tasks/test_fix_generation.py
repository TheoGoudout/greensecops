"""Unit tests for fix_generation helpers."""

from types import SimpleNamespace

from app.models import LLMProvider
from app.workers.patch_utils import apply_patch
from app.workers.tasks.fix_generation import (
    _is_valid_workflow_yaml,
    _resolve_llm_provider,
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


def test_non_applying_patch_is_rejected() -> None:
    patch = "@@ -100,1 +100,1 @@\n-nonexistent line\n+replacement\n"
    assert apply_patch(_WORKFLOW, patch) is None


def test_patched_invalid_yaml_is_rejected() -> None:
    # Replace the first line with structurally broken YAML
    patch = "@@ -1,1 +1,1 @@\n-name: CI\n+{ invalid: yaml: [}\n"
    patched = apply_patch(_WORKFLOW, patch)
    assert patched is not None
    assert _is_valid_workflow_yaml(patched) is False


def test_good_patch_yields_valid_yaml() -> None:
    patch = "@@ -5,1 +5,2 @@\n     runs-on: ubuntu-latest\n+    timeout-minutes: 15\n"
    patched = apply_patch(_WORKFLOW, patch)
    assert patched is not None
    assert _is_valid_workflow_yaml(patched) is True


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
