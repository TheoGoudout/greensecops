FIX_SYSTEM_PROMPT = """You are a GitHub Actions workflow expert. Fix issues in a CI/CD workflow YAML file.

Return your answer using EXACTLY this format — no JSON, no markdown, no extra explanation:

<full_content>
<complete fixed YAML with ALL issues addressed>
</full_content>

Rules for <full_content>:
- Must be the complete fixed YAML with ALL issues addressed
- Preserve ALL existing YAML comments exactly as they appear
- Preserve the trailing newline at the end of the file
- Ensure the result is valid GitHub Actions YAML syntax
- When pinning an action to a commit SHA, append the original tag as an inline comment: `uses: owner/action@<SHA> # <tag>`
- CRITICAL: Only use SHAs from the "Known action commit SHAs" section. If you add an action whose SHA is NOT listed there, use its tag reference (e.g., `uses: actions/cache@v4`) — do NOT invent or guess a SHA.
- When adding a new action or upgrading one, prefer the latest version listed in the "Known action commit SHAs" section
- CRITICAL: Never remove `fetch-depth: 0` from a checkout step if the job contains any step that uses `--from-ref` or invokes `prek`
- Make the minimum changes required to fix the listed issues; leave unrelated lines untouched"""

FIX_USER_PROMPT_TEMPLATE = """Fix ALL of the following issues in this GitHub Actions workflow:

**Issues to fix:**
{issues_block}

**Current workflow YAML:**
```yaml
{workflow_content}
```

Return only the <full_content> block — no markdown, no explanation."""


def build_fix_prompt(
    workflow_content: str,
    issues: list,
    action_sha_map: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Returns (system_prompt, user_prompt) for one or more issues."""
    issues_block = "\n".join(
        f"{i + 1}. [{issue.severity.value.upper()}] {issue.message}"
        f" (rule: {issue.rule.slug if issue.rule else 'unknown'}"
        f", job: {issue.job or 'n/a'}, step: {issue.step or 'n/a'})"
        for i, issue in enumerate(issues)
    )
    user_prompt = FIX_USER_PROMPT_TEMPLATE.format(
        issues_block=issues_block,
        workflow_content=workflow_content,
    )
    if action_sha_map:
        sha_block = "\n".join(
            f"- {ref}  →  {sha} # {ref.split('@', 1)[1]}"
            for ref, sha in sorted(action_sha_map.items())
        )
        user_prompt += (
            f"\n\n**Known action commit SHAs — use these exact replacements when pinning"
            f" (SHA + tag comment), do not invent SHAs:**\n{sha_block}"
        )
    return FIX_SYSTEM_PROMPT, user_prompt
