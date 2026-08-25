"""Tests for the fix-generation prompt builder."""

from types import SimpleNamespace

from app.models.enums import Severity
from app.services.llm.fix_prompt import build_fix_prompt


def _issue(message: str = "Unpinned action", slug: str = "unpinned-actions") -> object:
    return SimpleNamespace(
        severity=Severity.high,
        message=message,
        rule=SimpleNamespace(slug=slug),
        job="build",
        step="Checkout",
    )


def test_system_prompt_forbids_bumping_already_referenced_action_versions() -> None:
    system_prompt, _ = build_fix_prompt("name: CI\n", [_issue()])
    assert (
        "Never change the version/tag of an action already referenced" in system_prompt
    )
    assert "Dependabot" in system_prompt


def test_system_prompt_no_longer_tells_llm_to_prefer_latest_when_upgrading() -> None:
    system_prompt, _ = build_fix_prompt("name: CI\n", [_issue()])
    assert "upgrading one, prefer the latest version" not in system_prompt


def test_user_prompt_labels_sha_map_as_existing_versions_not_latest() -> None:
    _, user_prompt = build_fix_prompt(
        "      - uses: actions/checkout@v3\n",
        [_issue()],
        action_sha_map={"actions/checkout@v3": "a" * 40},
    )
    assert "actions/checkout@v3" in user_prompt
    assert "exact versions already used in this workflow" in user_prompt


def test_user_prompt_omits_sha_block_when_no_actions_resolved() -> None:
    _, user_prompt = build_fix_prompt("name: CI\n", [_issue()], action_sha_map=None)
    assert "Known action commit SHAs" not in user_prompt
