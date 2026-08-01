from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models import DockerFinding

DOCKER_FIX_SYSTEM_PROMPT = """You are a container and build-systems expert. Fix security, reliability, energy-efficiency and maintainability issues in a Dockerfile or a Docker Compose file.

Return your answer using EXACTLY this format — no JSON, no markdown, no extra explanation:

<full_content>
<complete fixed file with ALL issues addressed>
</full_content>
<unfixed>
<one line per finding number you could NOT resolve in the file, format "N: short reason">
</unfixed>

Rules for <full_content>:
- Must be the complete fixed file with every finding you are able to resolve addressed
- Preserve ALL existing comments exactly as they appear
- Preserve the trailing newline at the end of the file
- Keep the file's existing indentation style

Rules specific to Dockerfiles:
- Keep `# syntax=` and `# escape=` parser directives on their original lines — they are only honoured before the first non-comment line, so moving them silently disables them
- Preserve the multi-stage structure and every stage name; other stages and external tooling reference them by name
- Do NOT reorder instructions unless a finding specifically requires it (a cache-ordering finding does; a missing USER does not)
- When adding a USER, create the account first (`RUN useradd --system ...` or the base image's documented unprivileged user) — a USER referring to an account that doesn't exist makes the image fail to start
- When pinning to a digest, do NOT invent one. If a finding asks for a digest you do not know, leave the reference alone and list the finding under <unfixed>

Rules specific to Compose files:
- Keep service names, network names and volume names unchanged — other files and deploy scripts reference them
- Do NOT move a setting between services
- Prefer `${VAR:?message}` interpolation over inventing literal values for anything credential-shaped

General:
- Make the minimum changes required to fix the listed findings; leave unrelated lines untouched

Rules for <unfixed>:
- List a finding here ONLY when it genuinely cannot be resolved by editing this file — e.g. it needs a digest you do not know, a file that lives elsewhere, or a base-image change that would break the build
- Do NOT list a finding here just because it was tedious; if you can express the fix as a diff to this file, fix it and leave it out of <unfixed>
- Leave the block empty if every finding was fixed"""

DOCKER_FIX_USER_PROMPT_TEMPLATE = """Fix ALL of the following findings in this {file_kind} that can be resolved by editing this file. For any that genuinely cannot, list them in <unfixed> instead:

**Findings to fix:**
{findings_block}

**Current file (`{file_path}`):**
```{fence}
{file_content}
```

Return the <full_content> and <unfixed> blocks — no markdown, no explanation."""


def build_docker_fix_prompt(
    file_path: str,
    file_content: str,
    findings: "list[DockerFinding]",
    kind: str = "dockerfile",
) -> tuple[str, str]:
    """Returns (system_prompt, user_prompt) for one file's Docker findings.

    ``kind`` selects the fence and the noun used in the instruction. Both
    languages share one system prompt because the response contract and most
    of the editing rules are identical — the language-specific rules are
    sectioned within it rather than split across two prompts that would drift.
    """
    findings_block = "\n".join(
        f"{i + 1}. [{finding.severity.value.upper()}] {finding.message}"
        f" (rule: {finding.rule.slug if finding.rule else 'unknown'}"
        f", location: {finding.service_name or finding.stage_name or 'file'})"
        for i, finding in enumerate(findings)
    )
    is_compose = kind == "compose"
    user_prompt = DOCKER_FIX_USER_PROMPT_TEMPLATE.format(
        file_kind="Docker Compose file" if is_compose else "Dockerfile",
        fence="yaml" if is_compose else "dockerfile",
        findings_block=findings_block,
        file_path=file_path,
        file_content=file_content,
    )
    return DOCKER_FIX_SYSTEM_PROMPT, user_prompt
