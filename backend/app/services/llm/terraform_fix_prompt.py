from typing import TYPE_CHECKING

from .remediation import remediation_block

if TYPE_CHECKING:
    from app.models import TerraformFinding

TERRAFORM_FIX_SYSTEM_PROMPT = """You are a Terraform and cloud infrastructure expert. Fix security, reliability, cost and maintainability issues in a Terraform (.tf) file.

Return your answer using EXACTLY this format — no JSON, no markdown, no extra explanation:

<full_content>
<complete fixed HCL with ALL issues addressed>
</full_content>
<unfixed>
<one line per finding number you could NOT resolve in the diff, format "N: short reason">
</unfixed>

Rules for <full_content>:
- Must be the complete fixed Terraform file with every finding you are able to resolve addressed
- Preserve ALL existing HCL comments exactly as they appear
- Preserve the trailing newline at the end of the file
- Ensure the result is valid Terraform (HCL2) syntax
- Keep resource/variable/output/module addresses and names unchanged unless a finding specifically requires renaming — other files may reference them
- Do NOT change provider or module version constraints unless a finding is specifically about the version
- Make the minimum changes required to fix the listed findings; leave unrelated lines untouched

Rules for <unfixed>:
- List a finding here ONLY when it genuinely cannot be resolved by editing this file — e.g. it requires creating IAM policies in another file, wiring a KMS key that lives elsewhere, or a multi-file refactor
- Do NOT list a finding here just because it was tedious; if you can express the fix as a diff to this file, fix it and leave it out of <unfixed>
- A comment in the file explaining that the current state is deliberate — that a setting is omitted on purpose, or a flag left as it is for a stated reason — is the file's author answering this finding already. Report it under <unfixed>, quoting their reason. Never delete such a comment, and never make the change it argues against
- Leave the block empty if every finding was fixed"""

TERRAFORM_FIX_USER_PROMPT_TEMPLATE = """Fix ALL of the following findings in this Terraform file that can be resolved by editing this file. For any that genuinely cannot, list them in <unfixed> instead:

**Findings to fix:**
{findings_block}

**Current Terraform file (`{file_path}`):**
```hcl
{file_content}
```

Return the <full_content> and <unfixed> blocks — no markdown, no explanation."""


def build_terraform_fix_prompt(
    file_path: str,
    file_content: str,
    findings: "list[TerraformFinding]",
) -> tuple[str, str]:
    """Returns (system_prompt, user_prompt) for one or more Terraform findings."""
    findings_block = "\n".join(
        f"{i + 1}. [{finding.severity.value.upper()}] {finding.message}"
        f" (rule: {finding.rule.slug if finding.rule else 'unknown'}"
        f", resource: {finding.resource_address or 'n/a'})"
        for i, finding in enumerate(findings)
    )
    user_prompt = TERRAFORM_FIX_USER_PROMPT_TEMPLATE.format(
        findings_block=findings_block,
        file_path=file_path,
        file_content=file_content,
    )
    user_prompt += remediation_block(findings)
    return TERRAFORM_FIX_SYSTEM_PROMPT, user_prompt
