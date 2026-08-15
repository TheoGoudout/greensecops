from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models import Issue

FIX_SYSTEM_PROMPT = """You are a GitHub Actions workflow expert. Fix issues in a CI/CD workflow YAML file.

Return your answer using EXACTLY this format — no JSON, no markdown, no extra explanation:

<full_content>
<complete fixed YAML with ALL issues addressed>
</full_content>
<unfixed>
<one line per issue number you could NOT resolve in the diff, format "N: short reason">
</unfixed>

Rules for <full_content>:
- Must be the complete fixed YAML with every issue you are able to resolve addressed
- Preserve ALL existing YAML comments exactly as they appear
- Preserve the trailing newline at the end of the file
- Ensure the result is valid GitHub Actions YAML syntax
- When pinning an action to a commit SHA, append the original tag as an inline comment: `uses: owner/action@<SHA> # <tag>`
- CRITICAL: Only use SHAs from the "Known action commit SHAs" section. If you add an action whose SHA is NOT listed there, use its tag reference (e.g., `uses: actions/cache@v4`) — do NOT invent or guess a SHA.
- CRITICAL: Never change the version/tag of an action already referenced in the workflow (e.g. do not bump `actions/checkout@v3` to `@v4`) — pin it to a SHA at its existing tag only. Version upgrades are handled by Dependabot, not by this fix. Only use a "latest" entry from the list below when introducing an action that isn't already used anywhere in the workflow
- CRITICAL: Never remove `fetch-depth: 0` from a checkout step if the job contains any step that uses `--from-ref` or invokes `prek`
- CRITICAL: Never change a branch name. Branch names in `on:`, `base`, `ref` and similar keys are facts about this repository, not conventions — the default branch is given below, and any other branch named in the file is there deliberately
- CRITICAL: This is one file. Do not rename it, do not split it, and do not emit any other workflow — a workflow this repository does not have is not a fix
- Make the minimum changes required to fix the listed issues; leave unrelated lines untouched

Rules for <unfixed>:
- List an issue here ONLY when it genuinely cannot be resolved by editing this workflow file — e.g. it requires setting up cloud IAM/OIDC trust, creating repository secrets/variables outside this file, or a multi-file refactor
- Do NOT list an issue here just because it was tedious; if you can express the fix as a diff to this file, fix it and leave it out of <unfixed>
- Leave the block empty if every issue was fixed"""

FIX_USER_PROMPT_TEMPLATE = """Fix ALL of the following issues in this GitHub Actions workflow that can be resolved by editing this file. For any that genuinely cannot, list them in <unfixed> instead:

**Issues to fix:**
{issues_block}

**Current workflow YAML:**
```yaml
{workflow_content}
```

Return the <full_content> and <unfixed> blocks — no markdown, no explanation."""


def build_fix_prompt(
    workflow_content: str,
    issues: "list[Issue]",
    default_branch: str = "main",
    action_sha_map: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Returns (system_prompt, user_prompt) for one or more issues.

    ``default_branch`` is stated explicitly because the model has no way to know
    it and will otherwise fall back on its priors: a fix PR rewrote
    latest-changes.yml from `main` to `master`, which is the convention of the
    upstream template this repository came from and has never been the branch
    here.
    """
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
    user_prompt += (
        f"\n\n**This repository's default branch is `{default_branch}`.** Keep every"
        " branch name in the file exactly as it is."
    )
    if action_sha_map:
        sha_block = "\n".join(
            f"- {ref}  →  {sha} # {ref.split('@', 1)[1]}"
            for ref, sha in sorted(action_sha_map.items())
        )
        user_prompt += (
            f"\n\n**Known action commit SHAs for the exact versions already used in this"
            f" workflow (plus defaults for well-known actions you introduce fresh) — use"
            f" these exact replacements when pinning (SHA + tag comment), do not invent"
            f" SHAs:**\n{sha_block}"
        )
    return FIX_SYSTEM_PROMPT, user_prompt
