BATCH_FIX_SYSTEM_PROMPT = """You are a GitHub Actions workflow expert. Your task is to fix multiple issues in a CI/CD workflow YAML file in a single pass.

Rules:
- Return ONLY the complete fixed YAML file content — no explanation, no markdown code fences, no comments about what you changed
- Preserve all existing functionality
- Fix ALL listed issues in one go — your output must address every issue
- Make the minimum changes required to fix all reported issues
- Ensure the result is valid GitHub Actions YAML syntax
- Do not add unnecessary blank lines or reformat the entire file"""

BATCH_FIX_USER_PROMPT_TEMPLATE = """Fix ALL of the following issues in this GitHub Actions workflow in a single pass:

**Issues to fix:**
{issues_block}

**Current workflow YAML:**
```yaml
{workflow_content}
```

Return only the fixed YAML content that addresses every issue listed above."""


def build_batch_fix_prompt(
    workflow_content: str,
    issues: list,
) -> tuple[str, str]:
    """Returns (system_prompt, user_prompt) for a multi-issue batch fix."""
    issues_block = "\n".join(
        f"{i + 1}. [{issue.severity.value.upper()}] {issue.message}"
        f" (rule: {issue.rule.slug if issue.rule else 'unknown'}, category: {issue.category.value})"
        for i, issue in enumerate(issues)
    )
    user_prompt = BATCH_FIX_USER_PROMPT_TEMPLATE.format(
        issues_block=issues_block,
        workflow_content=workflow_content,
    )
    return BATCH_FIX_SYSTEM_PROMPT, user_prompt


FIX_SYSTEM_PROMPT = """You are a GitHub Actions workflow expert. Your task is to fix a specific issue in a CI/CD workflow YAML file.

Rules:
- Return ONLY the complete fixed YAML file content — no explanation, no markdown code fences, no comments about what you changed
- Preserve all existing functionality
- Make the minimum change required to fix the reported issue
- Ensure the fix is valid GitHub Actions YAML syntax
- Do not add unnecessary blank lines or reformat the entire file"""

FIX_USER_PROMPT_TEMPLATE = """Fix the following issue in this GitHub Actions workflow:

**Issue:** {issue_message}
**Rule:** {rule_slug}
**Category:** {category}
**Severity:** {severity}
{job_context}

**Current workflow YAML:**
```yaml
{workflow_content}
```

Return only the fixed YAML content."""


def build_fix_prompt(
    workflow_content: str,
    issue_message: str,
    rule_slug: str,
    category: str,
    severity: str,
    job_name: str | None = None,
) -> tuple[str, str]:
    """Returns (system_prompt, user_prompt) tuple."""
    job_context = f"**Job:** {job_name}" if job_name else ""
    user_prompt = FIX_USER_PROMPT_TEMPLATE.format(
        issue_message=issue_message,
        rule_slug=rule_slug,
        category=category,
        severity=severity,
        job_context=job_context,
        workflow_content=workflow_content,
    )
    return FIX_SYSTEM_PROMPT, user_prompt
