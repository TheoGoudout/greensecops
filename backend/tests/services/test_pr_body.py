"""Tests for the PR body builder service."""

from dataclasses import replace

import pytest

from app.services.pr_body import IssueInfo, ManualWorkInfo, build_pr_body


@pytest.fixture()
def single_issue() -> IssueInfo:
    return IssueInfo(
        rule_slug="unpinned-actions",
        rule_title="Unpinned Actions",
        category="security",
        severity="high",
        message="Action uses a mutable tag instead of a pinned SHA",
        workflow_path=".github/workflows/ci.yml",
        domain="ci_workflow",
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
            workflow_path=".github/workflows/ci.yml",
            domain="ci_workflow",
        ),
        IssueInfo(
            rule_slug="missing-timeout",
            rule_title="Missing Timeout",
            category="reliability",
            severity="medium",
            message="Job has no timeout",
            workflow_path=".github/workflows/ci.yml",
            domain="ci_workflow",
        ),
        IssueInfo(
            rule_slug="no-cache",
            rule_title="No Cache",
            category="performance",
            severity="low",
            message="Dependencies are not cached",
            workflow_path=".github/workflows/deploy.yml",
            domain="ci_workflow",
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
    # The page rego_autodoc actually writes: one directory per domain, and no
    # extension — the docs host redirects `.html` onto the extensionless path.
    assert (
        "https://wiki.example.com/rules/ci_workflow/security/unpinned-actions" in body
    )
    assert ".html" not in body
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
        workflow_path=".github/workflows/ci.yml",
    )
    body = build_pr_body(
        issues=[issue],
        fix_ids=["fix-1"],
        wiki_base_url="https://wiki.example.com/rules",
        frontend_host="https://app.example.com",
        bot_handle="@greensecops",
    )

    assert "Unknown-Level" in body


# ─── Multi-category tests (redis-py / celery scenario) ───────────────────────
# Issues reflect violations found in the real redis-py and celery workflows:
# security (excessive_token_permissions) and reliability (missing_timeout,
# unpinned_actions).


@pytest.fixture()
def redis_py_issues() -> list[IssueInfo]:
    """Five issues mirroring what would be found in the redis-py integration workflow."""
    return [
        IssueInfo(
            rule_slug="unpinned_actions",
            rule_title="Action Not Pinned to SHA",
            category="reliability",
            severity="high",
            message="Job 'lint' uses actions/checkout@v7 — mutable tag",
            workflow_path=".github/workflows/integration.yml",
        ),
        IssueInfo(
            rule_slug="missing_timeout",
            rule_title="Missing Job Timeout",
            category="reliability",
            severity="high",
            message="Job 'dependency-audit' has no timeout-minutes configured",
            workflow_path=".github/workflows/integration.yml",
        ),
        IssueInfo(
            rule_slug="missing_timeout",
            rule_title="Missing Job Timeout",
            category="reliability",
            severity="high",
            message="Job 'lint' has no timeout-minutes configured",
            workflow_path=".github/workflows/integration.yml",
        ),
        IssueInfo(
            rule_slug="missing_timeout",
            rule_title="Missing Job Timeout",
            category="reliability",
            severity="high",
            message="Job 'build-and-test-package' has no timeout-minutes configured",
            workflow_path=".github/workflows/integration.yml",
        ),
        IssueInfo(
            rule_slug="excessive_token_permissions",
            rule_title="Excessive Token Permissions",
            category="security",
            severity="critical",
            message="Workflow grants write-all GITHUB_TOKEN permissions",
            workflow_path=".github/workflows/integration.yml",
        ),
    ]


def test_pr_body_multi_category_renders_both_categories(
    redis_py_issues: list[IssueInfo],
) -> None:
    """PR body with reliability and security issues renders content from both categories."""
    body = build_pr_body(
        issues=redis_py_issues,
        fix_ids=[f"fix-{i}" for i in range(5)],
        wiki_base_url="https://wiki.example.com/rules",
        frontend_host="https://app.example.com",
        bot_handle="@greensecops",
    )

    # Both category names must appear (case-insensitive check via title-cased strings)
    body_lower = body.lower()
    assert "reliability" in body_lower
    assert "security" in body_lower

    # Rule titles from both categories appear
    assert "Action Not Pinned to SHA" in body or "action not pinned" in body_lower
    assert "Excessive Token Permissions" in body or "excessive token" in body_lower


def test_pr_body_all_five_issue_messages_present(
    redis_py_issues: list[IssueInfo],
) -> None:
    """All five issue messages are present in the PR body markdown."""
    body = build_pr_body(
        issues=redis_py_issues,
        fix_ids=[f"fix-{i}" for i in range(5)],
        wiki_base_url="https://wiki.example.com/rules",
        frontend_host="https://app.example.com",
        bot_handle="@greensecops",
    )

    for issue in redis_py_issues:
        assert issue.message in body, f"Expected message not found: {issue.message!r}"


# ─── Grouping by workflow file ───────────────────────────────────────────────


def test_build_pr_body_groups_issues_under_their_workflow_file(
    issues: list[IssueInfo],
) -> None:
    """A multi-file PR renders one collapsible section per workflow path,
    not one flat table — so it's clear which file each row belongs to."""
    body = build_pr_body(
        issues=issues,
        fix_ids=["fix-1", "fix-2", "fix-3"],
        wiki_base_url="https://wiki.example.com/rules",
        frontend_host="https://app.example.com",
        bot_handle="@greensecops",
    )

    assert body.count("<details") == 2
    ci_idx = body.index(".github/workflows/ci.yml")
    deploy_idx = body.index(".github/workflows/deploy.yml")
    # Each path's own issues are near its own heading, not interleaved.
    assert ci_idx < body.index("Unpinned Actions") < deploy_idx
    assert deploy_idx < body.index("No Cache")


def test_build_pr_body_single_workflow_still_wraps_in_details(
    single_issue: IssueInfo,
) -> None:
    body = build_pr_body(
        issues=[single_issue],
        fix_ids=["fix-id-1"],
        wiki_base_url="https://wiki.example.com/rules",
        frontend_host="https://app.example.com",
        bot_handle="@greensecops",
    )

    assert "<details" in body
    assert ".github/workflows/ci.yml" in body
    assert "(1 issue)" in body


def test_build_pr_body_omits_manual_work_section_when_nothing_is_unfixed(
    single_issue: IssueInfo,
) -> None:
    body = build_pr_body(
        issues=[single_issue],
        fix_ids=["fix-id-1"],
        wiki_base_url="https://wiki.example.com/rules",
        frontend_host="https://app.example.com",
        bot_handle="@greensecops",
    )

    assert "Needs Manual Work" not in body


def test_build_pr_body_lists_unfixed_issues_with_the_generator_note(
    single_issue: IssueInfo,
) -> None:
    """An issue the generator could not fix is named, not silently dropped.

    It was excluded from the "fixed" table and mentioned nowhere else, so the
    PR body showed no trace of it while the commit message still counted it.
    """
    body = build_pr_body(
        issues=[single_issue],
        fix_ids=["fix-id-1"],
        wiki_base_url="https://wiki.example.com/rules",
        frontend_host="https://app.example.com",
        bot_handle="@greensecops",
        manual_work=[
            ManualWorkInfo(
                rule_slug="self-hosted-runner-public-trigger",
                rule_title="Self-hosted Runner On Public Trigger",
                category="security",
                severity="critical",
                message="Self-hosted runner reachable from a fork PR",
                workflow_path=".github/workflows/ci.yml",
                note="Moving to a hosted runner changes where your builds run.",
            )
        ],
        review_url="https://app.example.com/repositories/abc/static-analysis",
    )

    assert "## Needs Manual Work" in body
    assert "Self-hosted Runner On Public Trigger" in body
    assert "Moving to a hosted runner changes where your builds run." in body
    # The link that answers "so what do I do about it".
    assert "https://app.example.com/repositories/abc/static-analysis" in body
    # Still separate from what the PR did change.
    assert body.index("## Issues Fixed") < body.index("## Needs Manual Work")
    assert body.index("## Needs Manual Work") < body.index("## How to Interact")


def test_build_pr_body_manual_work_falls_back_when_the_generator_gave_no_note() -> None:
    body = build_pr_body(
        issues=[],
        fix_ids=[],
        wiki_base_url="https://wiki.example.com/rules",
        frontend_host="https://app.example.com",
        bot_handle="@greensecops",
        manual_work=[
            ManualWorkInfo(
                rule_slug="missing-timeout",
                rule_title="Missing Timeout",
                category="reliability",
                severity="medium",
                message="Job has no timeout",
                workflow_path=".github/workflows/ci.yml",
                note=None,
            )
        ],
    )

    assert "could not resolve this within the file" in body
    # No review_url given: the section still renders, just without the link.
    assert "Review these issues in context" not in body


def test_a_rule_link_names_its_domain(single_issue: IssueInfo) -> None:
    """Every link in every automated PR used to 404.

    The docs are written to ``rules/<domain>/<category>/<slug>`` because a slug
    is unique only within a domain — ``rds_not_encrypted`` is a Terraform rule
    *and* a cloud rule. The link dropped the domain and appended ``.html``, so
    it pointed at a path that has never existed.
    """
    body = build_pr_body(
        issues=[single_issue],
        fix_ids=["fix-id-1"],
        wiki_base_url="https://docs.example.com/rules",
        frontend_host="https://app.example.com",
        bot_handle="@greensecops",
    )

    assert (
        "[Unpinned Actions](https://docs.example.com/rules/ci_workflow/security/unpinned-actions)"
        in body
    )


def test_a_finding_without_a_rule_is_not_linked_anywhere(
    single_issue: IssueInfo,
) -> None:
    """There is no page for it, and a link to a 404 is worse than no link."""
    orphan = replace(single_issue, domain=None, rule_title="Fix")

    body = build_pr_body(
        issues=[orphan],
        fix_ids=["fix-id-1"],
        wiki_base_url="https://docs.example.com/rules",
        frontend_host="https://app.example.com",
        bot_handle="@greensecops",
    )

    assert "| Fix |" in body
    assert "https://docs.example.com/rules" not in body


def test_an_unfixed_issue_is_linked_the_same_way(single_issue: IssueInfo) -> None:
    """The "needs manual work" table had its own copy of the broken URL."""
    manual = ManualWorkInfo(
        rule_slug="no_reusable_workflow",
        rule_title="No Reusable Workflow",
        category="maintainability",
        severity="low",
        message="Duplicated job definitions",
        workflow_path=".github/workflows/ci.yml",
        domain="ci_workflow",
        note="Extracting the shared job needs a judgement call.",
    )

    body = build_pr_body(
        issues=[single_issue],
        fix_ids=["fix-id-1"],
        wiki_base_url="https://docs.example.com/rules",
        frontend_host="https://app.example.com",
        bot_handle="@greensecops",
        manual_work=[manual],
    )

    assert (
        "https://docs.example.com/rules/ci_workflow/maintainability/no_reusable_workflow"
        in body
    )
    assert ".html" not in body
