"""Tests for the fix-generation prompt builder."""

from types import SimpleNamespace

from app.models.enums import Severity
from app.services.llm.fix_prompt import build_fix_prompt


def _issue(
    message: str = "Unpinned action",
    slug: str = "unpinned-actions",
    remediation: str | None = None,
) -> object:
    return SimpleNamespace(
        severity=Severity.high,
        message=message,
        rule=SimpleNamespace(slug=slug, remediation=remediation),
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


# ─── the rule author's remediation ───────────────────────────────────────────
#
# The finding message says what is wrong in one line; the rule's own
# `custom.examples.fix` says how to put it right, caveats included. Sending only
# the former is how plain `paths:` filters reached workflows that are required
# status checks — the rule's fix text says to use `paths-ignore` there, and the
# model never saw it.


def test_user_prompt_carries_the_rules_own_remediation() -> None:
    _, user_prompt = build_fix_prompt(
        "name: CI\n",
        [
            _issue(
                slug="push_trigger_without_path_filter",
                remediation="Use paths-ignore where a required check is involved.",
            )
        ],
    )
    assert "Use paths-ignore where a required check is involved." in user_prompt
    assert "`push_trigger_without_path_filter`" in user_prompt


def test_remediation_appears_once_per_rule_not_once_per_finding() -> None:
    """One Compose file produced twenty-one findings on a single rule.

    Repeating the paragraph per finding would crowd out the file the model is
    supposed to be rewriting, so it is deduplicated by slug.
    """
    text = "Add a tmpfs for the paths the process writes."
    _, user_prompt = build_fix_prompt(
        "name: CI\n",
        [_issue(slug="not_hardened", remediation=text) for _ in range(5)],
    )
    assert user_prompt.count(text) == 1


def test_user_prompt_omits_the_block_when_no_rule_carries_remediation() -> None:
    """Rows seeded before `rule.remediation` existed have none."""
    _, user_prompt = build_fix_prompt("name: CI\n", [_issue()])
    assert "How to fix these rules" not in user_prompt


def test_system_prompt_routes_a_deliberate_comment_to_unfixed() -> None:
    """A comment saying the current state is deliberate answers the finding.

    Two fix PRs deleted exactly such a comment and then made the change it
    argued against.
    """
    system_prompt, _ = build_fix_prompt("name: CI\n", [_issue()])
    assert "explaining that the current state is deliberate" in system_prompt
    assert "Never delete such a comment" in system_prompt
