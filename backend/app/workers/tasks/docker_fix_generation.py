import asyncio
import logging
import uuid
from typing import TYPE_CHECKING

from sqlmodel import Session, select

from app.core.db import engine
from app.models import (
    DockerBuildEnrichment,
    DockerFinding,
    DockerFix,
    DockerTarget,
    Repository,
)
from app.models.enums import FixStatus
from app.services import state_machines as sm
from app.services.docker.compose_parser import parse_compose_content
from app.services.docker.dockerfile_parser import parse_dockerfile_content
from app.services.docker.merge import COMPOSE, classify_docker_file
from app.workers.celery_app import celery_app
from app.workers.tasks.docker_analysis import _fetch_docker_files
from app.workers.tasks.fix_generation import (
    _parse_llm_response,
    _parse_unfixed_issues,
    restore_trailing_whitespace,
)

if TYPE_CHECKING:
    from app.services.llm.base import LLMResponse

logger = logging.getLogger(__name__)

INVALID_DOCKERFILE_ERROR = "LLM returned an unparseable Dockerfile"
INVALID_COMPOSE_ERROR = "LLM returned invalid Compose YAML"
MISSING_CONTENT_ERROR = "LLM response missing file content"
FILE_NOT_FOUND_ERROR = "File no longer present in the Docker target"


def _reparses(file_path: str, content: str) -> bool:
    """True when the rewritten file still parses as what it claims to be.

    The whole point of the gate: delivery pushes this content to a real branch,
    so an LLM rewrite that no longer parses would break the user's build. Uses
    the production parsers, not a lenient re-check, so anything the scanner
    would choke on is rejected here first.
    """
    if classify_docker_file(file_path) == COMPOSE:
        return parse_compose_content(file_path, content) is not None
    return parse_dockerfile_content(file_path, content) is not None


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

        target = session.get(DockerTarget, target_id)
        if not target:
            return {"status": "error", "detail": "docker_target_not_found"}
        repo = session.get(Repository, target.repo_id)
        if not repo:
            return {"status": "error", "detail": "repository_not_found"}

        file_path = resolved_path

        # The route creates one pending fix per (target, file). A file whose
        # fix is in any other state has no pending row and is skipped here.
        fix = session.exec(
            select(DockerFix)
            .where(DockerFix.docker_target_id == target.id)
            .where(DockerFix.file_path == file_path)
            .where(DockerFix.status == FixStatus.pending)
        ).first()
        if fix is None:
            return {"status": "skipped", "detail": "no_pending_fix"}

        sm.advance(fix, sm.FixMachine, "start_generation")
        session.add(fix)
        session.commit()
        session.refresh(fix)

        # Docker files aren't persisted — fetch current source live, the same
        # way the scan worker does.
        try:
            fetched = _fetch_docker_files(repo, target.root_path)
        except Exception as exc:
            logger.exception("Failed to fetch docker files for fix %s: %s", fix.id, exc)
            sm.advance(fix, sm.FixMachine, "generation_failed")
            fix.error_message = str(exc)[:2000]
            session.add(fix)
            session.commit()
            return {"status": "failed", "fix_id": str(fix.id)}

        source = next((f for f in fetched if f.path == file_path), None)
        if source is None:
            sm.advance(fix, sm.FixMachine, "generation_failed")
            fix.error_message = FILE_NOT_FOUND_ERROR
            session.add(fix)
            session.commit()
            return {"status": "failed", "fix_id": str(fix.id)}

        kind = classify_docker_file(file_path) or "dockerfile"
        try:
            result = asyncio.run(
                _generate_docker_fix(
                    file_path=file_path,
                    file_content=source.content,
                    findings=findings,
                    kind=kind,
                    provider_str=fix.llm_provider.value,
                    model_str=fix.llm_model,
                    enrichments=enrichments,
                )
            )
        except Exception as exc:
            logger.exception("Docker fix generation failed for %s: %s", fix.id, exc)
            sm.advance(fix, sm.FixMachine, "generation_failed")
            fix.error_message = str(exc)[:2000]
            session.add(fix)
            session.commit()
            return {"status": "failed", "fix_id": str(fix.id)}

        full_content = _parse_llm_response(result.content)
        generation_error: str | None = None
        if not full_content:
            generation_error = MISSING_CONTENT_ERROR
        else:
            full_content = restore_trailing_whitespace(source.content, full_content)
            if not _reparses(file_path, full_content):
                logger.warning(
                    "LLM full_content for %s does not re-parse; discarding", file_path
                )
                generation_error = (
                    INVALID_COMPOSE_ERROR
                    if kind == COMPOSE
                    else INVALID_DOCKERFILE_ERROR
                )

        fix.prompt_tokens = result.prompt_tokens
        fix.completion_tokens = result.completion_tokens
        fix.langsmith_run_id = result.run_id
        if generation_error:
            sm.advance(fix, sm.FixMachine, "generation_failed")
            fix.error_message = generation_error
        else:
            fix.full_content = full_content
            sm.advance(fix, sm.FixMachine, "generation_succeeded")
            # Parsed for parity with the workflow flow; Docker findings carry
            # no manual-work flag yet, so it's informational only.
            _parse_unfixed_issues(result.content)
        session.add(fix)
        session.commit()

        logger.info(
            "Docker fix generation for %d finding(s) in %s: %s",
            len(findings),
            file_path,
            fix.status.value,
        )
        return {"status": fix.status.value, "fix_id": str(fix.id)}


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


async def _generate_docker_fix(
    file_path: str,
    file_content: str,
    findings: list[DockerFinding],
    kind: str,
    provider_str: str,
    model_str: str,
    enrichments: list[DockerBuildEnrichment] | None = None,
) -> "LLMResponse":
    from app.services.llm.catalog import get_provider
    from app.services.llm.docker_fix_prompt import build_docker_fix_prompt

    provider = get_provider(provider=provider_str, model=model_str)
    system_prompt, user_prompt = build_docker_fix_prompt(
        file_path=file_path,
        file_content=file_content,
        findings=findings,
        kind=kind,
        runtime_findings=enrichments,
    )
    return await provider.generate(system_prompt, user_prompt)
