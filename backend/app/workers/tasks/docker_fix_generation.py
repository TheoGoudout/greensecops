import asyncio
import logging
import uuid
from typing import TYPE_CHECKING

from sqlmodel import Session

from app.core.db import engine
from app.models import DockerBuildEnrichment, DockerFinding, DockerTarget, Repository
from app.services.docker.compose_parser import parse_compose_content
from app.services.docker.dockerfile_parser import parse_dockerfile_content
from app.services.docker.merge import COMPOSE, classify_docker_file, merge_docker_files
from app.services.docker.registry import resolve_base_image_digests
from app.services.engines import DOCKER_ENGINE
from app.services.file_fix_generation import (
    MISSING_CONTENT_ERROR as MISSING_CONTENT_ERROR,  # re-exported for callers/tests
)
from app.services.file_fix_generation import (
    generate_file_fix,
    load_findings,
    make_rescan,
)
from app.services.github.fetch import fetch_docker_files as _fetch_docker_files
from app.services.opa.evaluator import evaluate_docker
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.services.llm.docker_fix_prompt import RepositoryFacts

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


def _repository_facts(
    session: Session, target_id: uuid.UUID
) -> "RepositoryFacts | None":
    """The repository a Docker target belongs to, as prompt facts.

    ``missing_oci_labels`` asks for a label pointing at "the repository URL",
    and the prompt had no repository in it — so the model reached for the URL
    in the rule's own example and every fixed image claimed to come from
    ``github.com/example/app``.

    ``None`` when the target or its repository has gone: a missing fact must
    leave the label unwritten, never guessed.
    """
    from app.services.llm.docker_fix_prompt import RepositoryFacts

    target = session.get(DockerTarget, target_id)
    if target is None:
        return None
    repo = session.get(Repository, target.repo_id)
    if repo is None:
        return None
    return RepositoryFacts.from_full_name(repo.full_name)


def _base_image_digests(path: str, content: str) -> dict[str, str]:
    """Digests for the unpinned base images in ``content``, looked up live.

    Resolved here rather than at scan time because the fix rewrites the file
    the model is looking at now, and a digest recorded days ago may no longer
    be what the tag points at. A Compose file has no ``FROM`` to resolve, and a
    registry that will not answer leaves the map empty — the prompt then offers
    nothing, and the model is told to leave those references alone.

    Never raises: an unreachable registry must cost the fix its digests, not
    the whole rewrite.
    """
    if classify_docker_file(path) == COMPOSE:
        return {}
    parsed = parse_dockerfile_content(path, content)
    if parsed is None:
        return {}
    try:
        return asyncio.run(resolve_base_image_digests(parsed))
    except Exception:
        logger.warning("Base image digest lookup failed for %s", path, exc_info=True)
        return {}


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
        findings = load_findings(session, DockerFinding, finding_ids)
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

        # Read inside the session that is still open: `generate_file_fix` opens
        # its own and hands `build_prompt` only the file, so the repository has
        # to be captured here or the prompt cannot name it.
        repository = _repository_facts(session, target_id)

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
            repository=repository,
            base_image_digests=_base_image_digests(path, content),
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
        make_rescan(merge_docker_files, evaluate_docker),
    )
