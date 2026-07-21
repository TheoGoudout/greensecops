"""Tests for _inject_action_into_workflow helper."""

from app.api.routes.repositories import _inject_action_into_workflow


def test_inject_into_simple_workflow() -> None:
    raw = (
        "on: push\n"
        "jobs:\n"
        "  build:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - run: echo hello\n"
    )
    result, modified = _inject_action_into_workflow(raw)
    assert modified is True
    assert "greensecops/telemetry@v1" in result
    assert "GreenSecOps Telemetry" in result


def test_inject_already_present_adds_permissions_only() -> None:
    raw = (
        "on: push\n"
        "jobs:\n"
        "  build:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: greensecops/telemetry@v1\n"
        "      - run: echo hello\n"
    )
    result, modified = _inject_action_into_workflow(raw)
    assert modified is True
    assert result.count("greensecops/telemetry@v1") == 1
    assert "id-token: write" in result


def test_inject_action_and_permissions_present_skips() -> None:
    raw = (
        "on: push\n"
        "jobs:\n"
        "  build:\n"
        "    runs-on: ubuntu-latest\n"
        "    permissions:\n"
        "      id-token: write\n"
        "    steps:\n"
        "      - uses: greensecops/telemetry@v1\n"
        "      - run: echo hello\n"
    )
    result, modified = _inject_action_into_workflow(raw)
    assert modified is False
    assert result == raw


def test_inject_invalid_yaml_returns_unmodified() -> None:
    raw = ": : : not valid yaml {{{"
    result, modified = _inject_action_into_workflow(raw)
    assert modified is False
    assert result == raw


def test_inject_non_dict_yaml_returns_unmodified() -> None:
    raw = "- item1\n- item2\n"
    result, modified = _inject_action_into_workflow(raw)
    assert modified is False
    assert result == raw


def test_inject_no_jobs_key_returns_unmodified() -> None:
    raw = "on: push\nname: CI\n"
    result, modified = _inject_action_into_workflow(raw)
    assert modified is False
    assert result == raw


def test_inject_jobs_not_dict_returns_unmodified() -> None:
    raw = "on: push\njobs:\n  - step1\n"
    result, modified = _inject_action_into_workflow(raw)
    assert modified is False
    assert result == raw


def test_inject_multiple_jobs() -> None:
    raw = (
        "on: push\n"
        "jobs:\n"
        "  build:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: echo test\n"
    )
    result, modified = _inject_action_into_workflow(raw)
    assert modified is True
    assert result.count("greensecops/telemetry@v1") == 2


def test_inject_job_no_steps_skipped() -> None:
    raw = "on: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n"
    result, modified = _inject_action_into_workflow(raw)
    assert modified is False


def test_inject_job_empty_steps_skipped() -> None:
    raw = "on: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps: []\n"
    result, modified = _inject_action_into_workflow(raw)
    assert modified is False


def test_inject_mixed_jobs_some_already_present() -> None:
    raw = (
        "on: push\n"
        "jobs:\n"
        "  build:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: greensecops/telemetry@v1\n"
        "      - run: echo build\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: echo test\n"
    )
    result, modified = _inject_action_into_workflow(raw)
    assert modified is True
    assert result.count("greensecops/telemetry@v1") == 2


def test_inject_job_value_not_dict_skipped() -> None:
    raw = "on: push\njobs:\n  build: some-reusable-workflow\n"
    result, modified = _inject_action_into_workflow(raw)
    assert modified is False
    assert result == raw
