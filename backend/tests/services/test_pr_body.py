"""Tests for the PR body builder service."""

import pytest

from app.services.pr_body import IssueInfo, build_pr_body


@pytest.fixture()
def single_issue() -> IssueInfo:
    return IssueInfo(
        rule_slug="unpinned-actions",
        rule_title="Unpinned Actions",
        category="security",
        severity="high",
        message="Action uses a mutable tag instead of a pinned SHA",
    )


@pytest.fixture()
def issues() -> list[IssueInfo]:
    return [
        IssueInfo(
            rule_slug="unpinned-actions",
            rule_title="Unpinned Actions",
            category="security",
            severity="high",
            message="Action uses a mutable tag",
        ),
        IssueInfo(
            rule_slug="missing-timeout",
            rule_title="Missing Timeout",
            category="reliability",
            severity="medium",
            message="Job has no timeout",
        ),
        IssueInfo(
            rule_slug="no-cache",
            rule_title="No Cache",
            category="performance",
            severity="low",
            message="Dependencies are not cached",
        ),
    ]


def test_build_pr_body_contains_header(single_issue: IssueInfo) -> None:
    body = build_pr_body(
        issues=[single_issue],
        fix_ids=["fix-id-1"],
        wiki_base_url="https://wiki.example.com/rules",
        frontend_host="https://app.example.com",
        bot_handle="@greensecops",
    )

    assert "GreenSecOps" in body
    assert "Automated Fix" in body


def test_build_pr_body_includes_issue_row(single_issue: IssueInfo) -> None:
    body = build_pr_body(
        issues=[single_issue],
        fix_ids=["fix-id-1"],
        wiki_base_url="https://wiki.example.com/rules",
        frontend_host="https://app.example.com",
        bot_handle="@greensecops",
    )

    assert "Unpinned Actions" in body
    assert "https://wiki.example.com/rules/unpinned-actions" in body
    assert "Security" in body
    assert "High" in body
    assert "Action uses a mutable tag instead of a pinned SHA" in body


def test_build_pr_body_includes_severity_emoji(single_issue: IssueInfo) -> None:
    body = build_pr_body(
        issues=[single_issue],
        fix_ids=["fix-id-1"],
        wiki_base_url="https://wiki.example.com/rules",
        frontend_host="https://app.example.com",
        bot_handle="@greensecops",
    )

    assert "🟠" in body  # high severity emoji


def test_build_pr_body_includes_fix_ids(single_issue: IssueInfo) -> None:
    body = build_pr_body(
        issues=[single_issue],
        fix_ids=["abc-123"],
        wiki_base_url="https://wiki.example.com/rules",
        frontend_host="https://app.example.com",
        bot_handle="@greensecops",
    )

    assert "`abc-123`" in body


def test_build_pr_body_truncates_fix_ids_after_five() -> None:
    fix_ids = [f"fix-{i}" for i in range(8)]
    body = build_pr_body(
        issues=[],
        fix_ids=fix_ids,
        wiki_base_url="https://wiki.example.com/rules",
        frontend_host="https://app.example.com",
        bot_handle="@greensecops",
    )

    assert "3 more" in body


def test_build_pr_body_includes_bot_handle(single_issue: IssueInfo) -> None:
    body = build_pr_body(
        issues=[single_issue],
        fix_ids=["fix-id-1"],
        wiki_base_url="https://wiki.example.com/rules",
        frontend_host="https://app.example.com",
        bot_handle="@mybot",
    )

    assert "@mybot disable" in body
    assert "@mybot disable-all" in body


def test_build_pr_body_includes_frontend_link(single_issue: IssueInfo) -> None:
    body = build_pr_body(
        issues=[single_issue],
        fix_ids=["fix-id-1"],
        wiki_base_url="https://wiki.example.com/rules",
        frontend_host="https://app.example.com",
        bot_handle="@greensecops",
    )

    assert "https://app.example.com" in body


def test_build_pr_body_multiple_issues(issues: list[IssueInfo]) -> None:
    body = build_pr_body(
        issues=issues,
        fix_ids=["fix-1", "fix-2", "fix-3"],
        wiki_base_url="https://wiki.example.com/rules",
        frontend_host="https://app.example.com",
        bot_handle="@greensecops",
    )

    assert "Unpinned Actions" in body
    assert "Missing Timeout" in body
    assert "No Cache" in body
    # All three fix IDs within the 5-item limit
    assert "`fix-1`" in body
    assert "`fix-2`" in body
    assert "`fix-3`" in body


def test_build_pr_body_unknown_severity_has_empty_emoji() -> None:
    issue = IssueInfo(
        rule_slug="some-rule",
        rule_title="Some Rule",
        category="security",
        severity="unknown-level",
        message="Some message",
    )
    body = build_pr_body(
        issues=[issue],
        fix_ids=["fix-1"],
        wiki_base_url="https://wiki.example.com/rules",
        frontend_host="https://app.example.com",
        bot_handle="@greensecops",
    )

    assert "Unknown-Level" in body
