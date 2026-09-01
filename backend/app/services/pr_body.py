from dataclasses import dataclass

from app.models.enums import Severity

_SEVERITY_EMOJI: dict[str, str] = {
    "critical": "🔴",
    "high": "🟠",
    "medium": "🟡",
    "low": "🟢",
    "info": "⚪",
}

_SEVERITY_ORDER: dict[str, int] = {s.value: i for i, s in enumerate(Severity)}


@dataclass
class IssueInfo:
    rule_slug: str
    rule_title: str
    category: str
    severity: str
    message: str
    workflow_path: str
    line_start: int | None = None
    # Which Rego package the rule lives in — the first path segment of its
    # documentation page. ``None`` when the finding has no rule row at all, in
    # which case there is no page to link to.
    domain: str | None = None


@dataclass
class ManualWorkInfo(IssueInfo):
    """An issue the fix generator reported it could not resolve in this diff.

    Same shape as a fixed issue plus the generator's own reason, because the PR
    has to say what it *left* as plainly as what it changed.
    """

    note: str | None = None


_NO_NOTE = "The automated fix could not resolve this within the file."


def _rule_link(issue: IssueInfo, wiki_base_url: str) -> str:
    """The rule's title, linked to its documentation page.

    The page lives at ``rules/<domain>/<category>/<slug>``: ``rego_autodoc``
    writes one directory per domain, because a slug is unique only within one
    — ``rds_not_encrypted`` is a rule in Terraform *and* in cloud. The link
    here dropped the domain and appended ``.html``, so every rule in every
    automated PR pointed at a page that does not exist. The extension is gone
    too: the docs host serves the extensionless path and redirects ``.html``
    onto it, so the canonical form is the one without.

    A finding with no rule row has no page, and is rendered as plain text
    rather than as a link somewhere that would 404.
    """
    if not issue.domain:
        return issue.rule_title
    url = f"{wiki_base_url}/{issue.domain}/{issue.category}/{issue.rule_slug}"
    return f"[{issue.rule_title}]({url})"


def _issue_table(issues: list[IssueInfo], wiki_base_url: str) -> str:
    sorted_issues = sorted(
        issues, key=lambda i: (_SEVERITY_ORDER.get(i.severity, 99), i.rule_title)
    )
    rows = "\n".join(
        f"| {_rule_link(i, wiki_base_url)} "
        f"| {i.category.title()} "
        f"| {_SEVERITY_EMOJI.get(i.severity, '')} {i.severity.title()} "
        f"| {i.message} |"
        for i in sorted_issues
    )
    return f"| Rule | Category | Severity | Message |\n|------|----------|----------|---------|\n{rows}"


def _issues_by_workflow_section(issues: list[IssueInfo], wiki_base_url: str) -> str:
    """One collapsible section per workflow file, so a multi-file PR reads as
    "what changed in each file" instead of one undifferentiated table."""
    by_path: dict[str, list[IssueInfo]] = {}
    for issue in issues:
        by_path.setdefault(issue.workflow_path, []).append(issue)

    sections = []
    for path in sorted(by_path):
        path_issues = by_path[path]
        n = len(path_issues)
        sections.append(
            f"<details open>\n"
            f"<summary><code>{path}</code> ({n} issue{'s' if n != 1 else ''})</summary>\n\n"
            f"{_issue_table(path_issues, wiki_base_url)}\n\n"
            f"</details>"
        )
    return "\n\n".join(sections)


def _manual_work_section(
    manual_work: list[ManualWorkInfo],
    wiki_base_url: str,
    review_url: str | None,
) -> str:
    """The "still open" half of the PR: what this diff deliberately left alone.

    Without it the PR only ever showed what it fixed, so an issue the generator
    reported as unfixable simply vanished from the description — while the
    commit message beside it still counted it. A reviewer had no way to see
    that anything was outstanding, let alone what to do about it.
    """
    if not manual_work:
        return ""

    by_path: dict[str, list[ManualWorkInfo]] = {}
    for issue in manual_work:
        by_path.setdefault(issue.workflow_path, []).append(issue)

    sections = []
    for path in sorted(by_path):
        rows = "\n".join(
            f"| {_rule_link(i, wiki_base_url)} "
            f"| {_SEVERITY_EMOJI.get(i.severity, '')} {i.severity.title()} "
            f"| {i.note or _NO_NOTE} |"
            for i in sorted(
                by_path[path],
                key=lambda i: (_SEVERITY_ORDER.get(i.severity, 99), i.rule_title),
            )
        )
        n = len(by_path[path])
        sections.append(
            f"<details open>\n"
            f"<summary><code>{path}</code> ({n} issue{'s' if n != 1 else ''})"
            f"</summary>\n\n"
            f"| Rule | Severity | Why it needs you |\n"
            f"|------|----------|------------------|\n{rows}\n\n"
            f"</details>"
        )

    total = len(manual_work)
    body = (
        "---\n\n"
        "## Needs Manual Work\n\n"
        f"{total} issue{'s' if total != 1 else ''} in these files "
        f"{'were' if total != 1 else 'was'} analysed but **not** changed by this "
        "PR — they need a judgement call this diff cannot make for you.\n\n"
        + "\n\n".join(sections)
    )
    if review_url:
        body += f"\n\n🔗 [Review these issues in context]({review_url})"
    # Trailing blank line so the horizontal rule that follows in the template
    # is a rule and not a setext underline for whatever ended this section.
    return body + "\n\n"


def build_pr_body(
    issues: list[IssueInfo],
    fix_ids: list[str],
    wiki_base_url: str,
    frontend_host: str,
    bot_handle: str,
    app_name: str = "GreenSecOps",
    app_url: str = "https://greensecops.com",
    manual_work: list[ManualWorkInfo] | None = None,
    review_url: str | None = None,
) -> str:
    sections = _issues_by_workflow_section(issues, wiki_base_url)
    manual = _manual_work_section(manual_work or [], wiki_base_url, review_url)
    fix_ids_str = ", ".join(f"`{fid}`" for fid in fix_ids[:5])
    if len(fix_ids) > 5:
        fix_ids_str += f" and {len(fix_ids) - 5} more"

    return f"""\
## 🌿 {app_name} — Automated Fix

This PR was automatically generated by **[{app_name}]({app_url})**, a tool that continuously analyses your GitHub Actions workflows for security, performance, energy efficiency, reliability, and maintainability issues.

---

## Issues Fixed

{sections}

{manual}---

## How to Interact

Comment on this PR to control {app_name}:

| Command | Effect |
|---------|--------|
| `{bot_handle} disable` | Disable auto-fix PRs for **this repository** |
| `{bot_handle} disable-all` | Disable auto-fix PRs for **all your repositories** |

---

🔗 [View on {app_name}]({frontend_host}) · [Register for free]({frontend_host}/signup)

<sub>Fix IDs: {fix_ids_str}</sub>"""
