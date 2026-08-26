import uuid

from sqlmodel import Session

from app.core.db import engine
from app.models import DockerBuildEnrichment, DockerFinding
from app.services.docker.compose_parser import parse_compose_content
from app.services.docker.dockerfile_parser import parse_dockerfile_content
from app.services.docker.merge import COMPOSE, classify_docker_file
from app.services.engines import DOCKER_ENGINE
from app.services.file_fix_generation import (
    MISSING_CONTENT_ERROR as MISSING_CONTENT_ERROR,  # re-exported for callers/tests
)
from app.services.file_fix_generation import generate_file_fix
from app.services.github.fetch import fetch_docker_files as _fetch_docker_files
from app.workers.celery_app import celery_app

INVALID_DOCKERFILE_ERROR = "LLM returned an unparseable Dockerfile"
INVALID_COMPOSE_ERROR = "LLM returned invalid Compose YAML"


def _validate(
    file_path: str,
    original: str,  # noqa: ARG001 — the shared guard contract is differential
    content: str,
) -> str | None:
    """Only trust the rewrite if it still parses as what it claims to be.

    Uses the production parsers, not a lenient re-check, so anything the
    scanner would choke on is rejected here first.

    ``original`` is unused, as it is for Terraform: neither format has a value
    that must survive byte-identical. The argument exists because Ansible's
    guard is differential and the contract is shared.
    """
    if classify_docker_file(file_path) == COMPOSE:
        if parse_compose_content(file_path, content) is None:
            return INVALID_COMPOSE_ERROR
    elif parse_dockerfile_content(file_path, content) is None:
        return INVALID_DOCKERFILE_ERROR
    return None


def _load_enrichments(
    session: Session, enrichment_ids: list[str] | None
) -> list[DockerBuildEnrichment]:
    """Load measured evidence, skipping anything that has since been swept.

    ``docker_telemetry_analysis`` deletes and reinserts a telemetry row's
    enrichments on every re-run, so an id queued a moment ago can legitimately
    be gone by the time this task runs. That costs the prompt some evidence; it
    must not fail the fix.
    """
    if not enrichment_ids:
        return []
    loaded = [
        session.get(DockerBuildEnrichment, uuid.UUID(eid)) for eid in enrichment_ids
    ]
    return [e for e in loaded if e is not None]


@celery_app.task(name="docker_fix_generation.run", bind=True, max_retries=3)
def run_docker_fix_generation(
    self: object,  # noqa: ARG001
    finding_ids: list[str],
    enrichment_ids: list[str] | None = None,
    docker_target_id: str | None = None,
    file_path: str | None = None,
) -> dict[str, object]:
    """Single LLM call rewriting one Docker file to fix the given findings.

    The API route creates a pending ``DockerFix`` per file before queuing this
    task; it consumes that row. All ``finding_ids`` belong to one file of one
    target (the route groups by file path).

    ``enrichment_ids`` carry measured runtime evidence for the same file. They
    can ride alongside static findings — giving the model a real peak instead
    of a guess — or drive the call on their own, in which case the route must
    also pass ``docker_target_id`` and ``file_path`` because there is no
    finding to read them off.
    """
    with Session(engine) as session:
        loaded = [session.get(DockerFinding, uuid.UUID(fid)) for fid in finding_ids]
        findings = [f for f in loaded if f is not None]
        enrichments = _load_enrichments(session, enrichment_ids)
        if not findings and not enrichments:
            return {"status": "error", "detail": "no_findings_found"}

        # Findings are authoritative when present: they already encode the
        # target and file, and trusting them keeps every existing caller's
        # behaviour byte-identical.
        if findings:
            target_id = findings[0].docker_target_id
            resolved_path = findings[0].file_path
        elif docker_target_id and file_path:
            target_id = uuid.UUID(docker_target_id)
            resolved_path = file_path
        else:
            return {"status": "error", "detail": "no_target_for_runtime_fix"}

    def build_prompt(
        path: str, content: str, group: list[DockerFinding]
    ) -> tuple[str, str]:
        from app.services.llm.docker_fix_prompt import build_docker_fix_prompt

        return build_docker_fix_prompt(
            file_path=path,
            file_content=content,
            findings=group,
            kind=classify_docker_file(path) or "dockerfile",
            runtime_findings=enrichments,
        )

    return generate_file_fix(
        DOCKER_ENGINE,
        target_id,
        resolved_path,
        findings,
        # Passed in rather than held on the spec: this module-level name is the
        # seam the tests patch.
        _fetch_docker_files,
        build_prompt,
        _validate,
    )
