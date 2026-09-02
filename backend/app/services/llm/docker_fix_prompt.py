from dataclasses import dataclass
from typing import TYPE_CHECKING

from .remediation import remediation_block

if TYPE_CHECKING:
    from app.models import DockerBuildEnrichment, DockerFinding


@dataclass(frozen=True)
class RepositoryFacts:
    """What the model needs to know about the repository it is editing.

    Only facts, never guidance: the source URL and the image name are values
    that belong *in* the file, and without them the model has nothing to write
    but a placeholder.
    """

    full_name: str
    url: str

    @property
    def image_title(self) -> str:
        """The repository's own name, without the owner — the image's title."""
        return self.full_name.rsplit("/", 1)[-1]

    @classmethod
    def from_full_name(cls, full_name: str) -> "RepositoryFacts":
        return cls(full_name=full_name, url=f"https://github.com/{full_name}")


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
- CRITICAL: when pinning a base image to a digest, use ONLY a digest from the "Verified base image digests" section below, and keep the tag alongside it (`FROM image:tag@sha256:...`) so the pin stays reviewable. If a reference you need is not listed there, do NOT invent or guess a digest — leave that FROM alone and list the finding under <unfixed>
- For OCI annotations (`org.opencontainers.image.*`), use ONLY the values from the "Repository" section below. Never write an example or placeholder URL — a label pointing at someone else's repository is worse than no label, because tooling believes it
- Annotations whose value changes every build — `revision`, `created`, `version` — are not literals. Declare them as build arguments (`ARG` plus `LABEL org.opencontainers.image.revision=$VCS_REF`) or leave them out; hardcoding one bakes a lie into every later image

Rules specific to Compose files:
- Keep service names, network names and volume names unchanged — other files and deploy scripts reference them
- Do NOT move a setting between services
- Prefer `${VAR:?message}` interpolation over inventing literal values for anything credential-shaped

General:
- Make the minimum changes required to fix the listed findings; leave unrelated lines untouched
- When measured runtime facts are supplied, take the numbers from them. They come from observing the container actually run, so a limit derived from a measured peak is the point of the exercise — a round guess is what the measurement replaced

Rules for <unfixed>:
- List a finding here ONLY when it genuinely cannot be resolved by editing this file — e.g. it needs a digest you do not know, a file that lives elsewhere, or a base-image change that would break the build
- Do NOT list a finding here just because it was tedious; if you can express the fix as a diff to this file, fix it and leave it out of <unfixed>
- A comment in the file explaining that the current state is deliberate — that a setting is omitted on purpose, or a flag left as it is for a stated reason — is the file's author answering this finding already. Report it under <unfixed>, quoting their reason. Never delete such a comment, and never make the change it argues against
- Leave the block empty if every finding was fixed"""

DOCKER_FIX_USER_PROMPT_TEMPLATE = """Fix ALL of the following findings in this {file_kind} that can be resolved by editing this file. For any that genuinely cannot, list them in <unfixed> instead:

**Findings to fix:**
{findings_block}
{digest_block}{repository_block}{runtime_block}
**Current file (`{file_path}`):**
```{fence}
{file_content}
```

Return the <full_content> and <unfixed> blocks — no markdown, no explanation."""

DIGEST_HEADER = """
**Verified base image digests** — looked up from the registry just now. These are the only digests you may write; anything not listed here must keep its current reference:
{digest_block}
"""

REPOSITORY_HEADER = """
**Repository** — the real values for this file's OCI annotations. Use these exactly; do not substitute an example:
- `org.opencontainers.image.source`: {url}
- `org.opencontainers.image.url`: {url}
- `org.opencontainers.image.title`: {title}
"""

RUNTIME_EVIDENCE_HEADER = """
**Measured runtime facts** — observed while these containers actually ran in CI. Use these numbers rather than estimating:
{evidence_block}
"""

NO_STATIC_FINDINGS_PLACEHOLDER = (
    "(none from static analysis — the measured facts below are what to fix)"
)


def _build_runtime_block(enrichments: "list[DockerBuildEnrichment]") -> str:
    """Render measured evidence as a distinct section, not as more findings.

    Kept separate because the two are different kinds of claim: a static
    finding says the file is wrong, a measurement says what the container did.
    Collapsing them would invite the model to treat an observation as a defect
    to be edited away.
    """
    if not enrichments:
        return ""
    evidence_block = "\n".join(
        f"- [{e.rule_slug}] {e.evidence}\n  → {e.recommendation}" for e in enrichments
    )
    return RUNTIME_EVIDENCE_HEADER.format(evidence_block=evidence_block)


def _build_digest_block(digests: dict[str, str]) -> str:
    """Offer verified digests, the way the workflow prompt offers action SHAs.

    ``unpinned_base_image`` wants ``image:tag@sha256:...`` and the prompt could
    supply no digest, so the honest instruction was "leave it and report it
    unfixable" — which meant the rule was effectively never auto-fixed. With the
    real values in hand the model can pin, and "never invent one" still governs
    everything absent from this list.
    """
    if not digests:
        return ""
    digest_block = "\n".join(
        f"- {ref}  →  {ref}@{digest}" for ref, digest in sorted(digests.items())
    )
    return DIGEST_HEADER.format(digest_block=digest_block)


def _build_repository_block(repository: RepositoryFacts | None) -> str:
    """Name the repository being edited, so annotations can be true.

    ``missing_oci_labels`` asks for ``org.opencontainers.image.source``
    pointing at "the repository URL". With no repository in the prompt the
    model had no URL to point at and wrote the one from the rule's own example,
    so every fixed image claimed to come from ``github.com/example/app``.
    """
    if repository is None:
        return ""
    return REPOSITORY_HEADER.format(url=repository.url, title=repository.image_title)


def build_docker_fix_prompt(
    file_path: str,
    file_content: str,
    findings: "list[DockerFinding]",
    kind: str = "dockerfile",
    runtime_findings: "list[DockerBuildEnrichment] | None" = None,
    repository: RepositoryFacts | None = None,
    base_image_digests: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Returns (system_prompt, user_prompt) for one file's Docker findings.

    ``kind`` selects the fence and the noun used in the instruction. Both
    languages share one system prompt because the response contract and most
    of the editing rules are identical — the language-specific rules are
    sectioned within it rather than split across two prompts that would drift.

    ``runtime_findings`` are measured enrichments for the same file. They can
    accompany static findings, or stand alone: a measurement like "peaked at
    420 MB with no limit set" is actionable even when no static rule fired,
    which is the whole reason runtime telemetry can produce a fix at all.

    ``repository`` supplies the values an OCI annotation has to carry. It is
    optional because a caller that cannot resolve the repository must still be
    able to fix everything else — the model is then told nothing rather than
    told something wrong.

    ``base_image_digests`` maps ``image:tag`` to the digest it resolves to
    today. Same contract: only what is listed may be written, so an image that
    could not be resolved keeps its current reference.
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
        findings_block=findings_block or NO_STATIC_FINDINGS_PLACEHOLDER,
        digest_block=_build_digest_block(base_image_digests or {}),
        repository_block=_build_repository_block(repository),
        runtime_block=_build_runtime_block(runtime_findings or []),
        file_path=file_path,
        file_content=file_content,
    )
    user_prompt += remediation_block(findings)
    return DOCKER_FIX_SYSTEM_PROMPT, user_prompt
