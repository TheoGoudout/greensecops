"""Prompt for rewriting one Ansible file so its findings go away.

Diverges from the Terraform and Docker prompts in one respect, and it is the
same respect that gives this engine a differential fix guard: Ansible files
carry values that mean nothing to YAML and everything to Ansible. A Jinja
expression is just a string to the parser; a ``!vault`` tag is what separates
ciphertext from a base64-looking password. A rewrite can lose either and still
produce a file that parses cleanly.

So the rules below name both explicitly rather than trusting "make minimal
edits" to cover them. ``app/services/ansible/fix_guard.py`` enforces the same
two invariants after the fact — the prompt asks, the guard checks.
"""

from typing import TYPE_CHECKING

from .remediation import remediation_block

if TYPE_CHECKING:
    from app.models import AnsibleFinding

ANSIBLE_FIX_SYSTEM_PROMPT = """You are an Ansible expert. Fix security, reliability, energy-efficiency and maintainability issues in an Ansible file (a playbook, task file, handler file, variables file or galaxy requirements file).

Return your answer using EXACTLY this format — no JSON, no markdown, no extra explanation:

<full_content>
<complete fixed YAML with ALL issues addressed>
</full_content>
<unfixed>
<one line per finding number you could NOT resolve in the diff, format "N: short reason">
</unfixed>

Rules for <full_content>:
- Must be the complete fixed Ansible file with every finding you are able to resolve addressed
- Reproduce every Jinja expression (`{{ ... }}`, `{% ... %}`) EXACTLY as written unless a finding is specifically about it. You may add a filter to one — `{{ x }}` to `{{ x | quote }}` — but never drop a variable reference or rename a variable: other files resolve those names
- Reproduce every YAML tag (`!vault`, `!unsafe`) and its entire scalar EXACTLY. A `!vault` block is ciphertext; losing the tag turns it into a literal string and the play will authenticate with garbage
- Preserve ALL existing YAML comments exactly as they appear
- Preserve the leading `---` document marker if present, and the trailing newline at the end of the file
- Keep the file the same kind it already is: do not turn a task file into a playbook by wrapping it in a play, and do not unwrap a playbook into bare tasks
- Keep task `name:` values unchanged unless a finding is specifically about a name — handlers are notified by name, and `--start-at-task` refers to them
- Prefer fully-qualified collection names (`ansible.builtin.apt`) when adding a new module call, but do not churn existing short names that no finding mentions
- Use correct YAML indentation (2 spaces, sequences under their key) and valid Ansible module arguments
- Make the minimum changes required to fix the listed findings; leave unrelated lines untouched

Rules for <unfixed>:
- List a finding here ONLY when it genuinely cannot be resolved by editing this file — e.g. the checksum to pin belongs in a `defaults/main.yml` you cannot see, or the fix needs a variable defined in another role
- Do NOT list a finding here just because it was tedious; if you can express the fix as a diff to this file, fix it and leave it out of <unfixed>
- A comment in the file explaining that the current state is deliberate — that a setting is omitted on purpose, or a flag left as it is for a stated reason — is the file's author answering this finding already. Report it under <unfixed>, quoting their reason. Never delete such a comment, and never make the change it argues against
- Leave the block empty if every finding was fixed"""

ANSIBLE_FIX_USER_PROMPT_TEMPLATE = """Fix ALL of the following findings in this Ansible file that can be resolved by editing this file. For any that genuinely cannot, list them in <unfixed> instead:

**Findings to fix:**
{findings_block}

**Current Ansible file (`{file_path}`):**
```yaml
{file_content}
```

Return the <full_content> and <unfixed> blocks — no markdown, no explanation."""


def build_ansible_fix_prompt(
    file_path: str,
    file_content: str,
    findings: "list[AnsibleFinding]",
) -> tuple[str, str]:
    """Returns (system_prompt, user_prompt) for one or more Ansible findings."""
    findings_block = "\n".join(
        f"{i + 1}. [{finding.severity.value.upper()}] {finding.message}"
        f" (rule: {finding.rule.slug if finding.rule else 'unknown'}"
        # The task name is the locator a reader recognises, and the line number
        # disambiguates two tasks that share one. A file-level finding — an
        # unpinned galaxy requirement — has neither, so both degrade to 'n/a'.
        f", task: {finding.task_name or 'n/a'}"
        f", line: {finding.line_start or 'n/a'})"
        for i, finding in enumerate(findings)
    )
    user_prompt = ANSIBLE_FIX_USER_PROMPT_TEMPLATE.format(
        findings_block=findings_block,
        file_path=file_path,
        file_content=file_content,
    )
    user_prompt += remediation_block(findings)
    return ANSIBLE_FIX_SYSTEM_PROMPT, user_prompt
