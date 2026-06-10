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
