FIX_SYSTEM_PROMPT = """You are a GitHub Actions workflow expert. Fix issues in a CI/CD workflow YAML file.

Return ONLY valid JSON — no explanation, no markdown code fences, no prose.

Output format:
{
  "full_content": "<complete fixed YAML file>",
  "fixes": [
    {
      "fingerprint": "<issue fingerprint>",
      "diff": "<unified diff patch for this issue only>"
    }
  ]
}

Rules:
- "full_content" must be the complete fixed YAML with ALL issues addressed
- Each "diff" is a minimal unified diff in standard format covering exactly one issue:
    --- a/.github/workflows/name.yml
    +++ b/.github/workflows/name.yml
    @@ -N,M +N,M @@
     context
    -removed
    +added
- Preserve ALL existing YAML comments exactly as they appear
- Preserve the trailing newline at the end of the file
- Make the minimum changes required to fix each issue
- Ensure the result is valid GitHub Actions YAML syntax
- When pinning an action to a commit SHA, append the original tag as an inline comment: `uses: owner/action@<SHA> # <tag>`
- CRITICAL: Never remove `fetch-depth: 0` from a checkout step if the job contains any step that uses `--from-ref` or invokes `prek`"""

FIX_USER_PROMPT_TEMPLATE = """Fix ALL of the following issues in this GitHub Actions workflow:

**Issues to fix (include each fingerprint exactly as shown in your JSON output):**
{issues_block}

**Current workflow YAML:**
```yaml
{workflow_content}
```

Return only the JSON object — no markdown, no explanation."""


def build_fix_prompt(
    workflow_content: str,
    issues: list,
    action_sha_map: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Returns (system_prompt, user_prompt) for one or more issues."""
    issues_block = "\n".join(
        f"{i + 1}. [fingerprint: {issue.fingerprint or 'none'}] [{issue.severity.value.upper()}] {issue.message}"
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
