"""Unit tests for fix_generation helpers."""

from types import SimpleNamespace
from unittest.mock import patch

from app.models import LLMProvider
from app.workers.tasks.fix_generation import (
    _is_valid_workflow_yaml,
    _parse_llm_response,
    _record_batch_result,
    init_fix_batch,
    resolve_llm_provider,
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


# ─── resolve_llm_provider ────────────────────────────────────────────────────


def test_resolve_llm_provider_uses_provider_default_model() -> None:
    # A repo pinned to anthropic without a model must NOT fall back to an
    # OpenAI model name.
    repo = SimpleNamespace(
        llm_provider=LLMProvider.anthropic,
        llm_model=None,
        organization=None,
    )
    provider, model = resolve_llm_provider(repo)
    assert provider == "anthropic"
    assert "gpt" not in model


# ─── batch coordination ──────────────────────────────────────────────────────


class _FakeRedis:
    """Minimal in-memory stand-in for the sync redis client."""

    def __init__(self) -> None:
        self.store: dict[str, object] = {}

    def set(self, key: str, value: object, ex: int | None = None) -> None:
        self.store[key] = str(value)

    def get(self, key: str) -> str | None:
        return self.store.get(key)  # type: ignore[return-value]

    def sadd(self, key: str, *values: str) -> None:
        self.store.setdefault(key, set()).update(values)  # type: ignore[union-attr]

    def smembers(self, key: str) -> "set[str]":
        return self.store.get(key) or set()  # type: ignore[return-value]

    def expire(self, key: str, ttl: int) -> None:
        pass

    def decr(self, key: str) -> int:
        value = int(self.store.get(key, 0)) - 1  # type: ignore[arg-type]
        self.store[key] = str(value)
        return value

    def delete(self, *keys: str) -> None:
        for key in keys:
            self.store.pop(key, None)

    def close(self) -> None:
        pass


def test_batch_publishes_single_event_pair_when_last_task_ends() -> None:
    fake = _FakeRedis()
    with (
        patch("redis.from_url", return_value=fake),
        patch(
            "app.workers.tasks.fix_generation.events_pub.publish_event"
        ) as mock_publish,
    ):
        init_fix_batch("b1", 2)
        _record_batch_result("b1", "org", "repo", ["f1"], [], None)
        assert mock_publish.call_count == 0

        _record_batch_result("b1", "org", "repo", ["f2"], ["f3"], "boom")

    events = [call.args[0] for call in mock_publish.call_args_list]
    ready = [e for e in events if "error" not in e.data]
    failed = [e for e in events if "error" in e.data]
    assert len(ready) == 1
    assert set(ready[0].data["fix_ids"]) == {"f1", "f2"}
    assert len(failed) == 1
    assert failed[0].data["fix_ids"] == ["f3"]
    assert failed[0].data["error"] == "boom"


def test_batch_publishes_no_failed_event_when_all_ready() -> None:
    fake = _FakeRedis()
    with (
        patch("redis.from_url", return_value=fake),
        patch(
            "app.workers.tasks.fix_generation.events_pub.publish_event"
        ) as mock_publish,
    ):
        init_fix_batch("b2", 1)
        _record_batch_result("b2", "org", "repo", ["f1", "f2"], [], None)

    events = [call.args[0] for call in mock_publish.call_args_list]
    assert len(events) == 1
    assert set(events[0].data["fix_ids"]) == {"f1", "f2"}


def test_batch_fails_open_when_redis_unavailable() -> None:
    with (
        patch("redis.from_url", side_effect=RuntimeError("redis down")),
        patch(
            "app.workers.tasks.fix_generation.events_pub.publish_event"
        ) as mock_publish,
    ):
        _record_batch_result("b3", "org", "repo", ["f1"], ["f2"], "err")

    events = [call.args[0] for call in mock_publish.call_args_list]
    assert len(events) == 2
    ready = next(e for e in events if "error" not in e.data)
    failed = next(e for e in events if "error" in e.data)
    assert ready.data["fix_ids"] == ["f1"]
    assert failed.data["fix_ids"] == ["f2"]
