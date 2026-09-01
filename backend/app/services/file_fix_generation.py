"""Ask an LLM to rewrite one file so a target's findings go away.

Shared by the Terraform and Docker generation tasks. The two differ in only
three ways, all passed in: how to validate that what came back still parses,
what to call it when it doesn't, and how to build the prompt. The rest — claim
the pending fix row, fetch the file's current source, run the model, sanity
check the result, record tokens and status — was identical.

The file's source is fetched live rather than read from a row, because unlike
``WorkflowFile`` neither engine persists the files it scans.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from app.core.db import engine
from app.models import Repository
from app.models.enums import FixStatus
from app.services import state_machines as sm
from app.services.engines import EngineSpec
from app.services.llm.response import (
    parse_full_content,
    parse_unfixed_issues,
    restore_trailing_whitespace,
)

if TYPE_CHECKING:
    from app.services.llm.base import LLMResponse

logger = logging.getLogger(__name__)

MISSING_CONTENT_ERROR = "LLM response missing file content"
FILE_NOT_FOUND_ERROR = "File no longer present in the target"


def load_findings(session: Session, model: Any, finding_ids: list[str]) -> list[Any]:
    """Load one file's findings, with their rule already attached.

    Each task hands these rows to ``generate_file_fix`` after its own session
    has closed, so they arrive detached: an attribute the prompt builder reaches
    for that was not loaded here raises ``DetachedInstanceError`` instead of
    emitting a query. ``rule`` is the one relationship the prompts read
    (``finding.rule.slug``), so it is loaded up front.

    Ids that no longer resolve are dropped rather than failing the batch.
    """
    loaded = [
        session.get(model, uuid.UUID(fid), options=[selectinload(model.rule)])
        for fid in finding_ids
    ]
    return [f for f in loaded if f is not None]


def _fail(session: Session, fix: Any, message: str) -> dict[str, object]:
    sm.advance(fix, sm.FixMachine, "generation_failed")
    fix.error_message = message[:2000]
    session.add(fix)
    session.commit()
    return {"status": "failed", "fix_id": str(fix.id)}


def generate_file_fix(
    spec: EngineSpec,
    target_id: uuid.UUID,
    file_path: str,
    findings: list[Any],
    fetch_files: Callable[..., Any],
    build_prompt: Callable[[str, str, list[Any]], tuple[str, str]],
    validate: Callable[[str, str, str], str | None],
) -> dict[str, object]:
    """Run one LLM call rewriting ``file_path`` to fix ``findings``.

    ``validate`` receives ``(file_path, original_content, patched_content)``
    and returns an error message when the rewrite is unusable or ``None`` when
    it is fine. That gate matters: delivery pushes this content to a real
    branch, so an unparseable rewrite would break the user's build.

    It takes the original as well as the rewrite because a "still parses?"
    check is not enough for every engine. Ansible carries values that must
    survive byte-identical — Jinja expressions, ``!vault`` tags — and losing
    one produces a file that parses perfectly and does the wrong thing, so its
    guard has to diff the two. The original is fetched here rather than by the
    caller, so a closure in the task could not capture it.
    """
    with Session(engine) as session:
        target = session.get(spec.target_model, target_id)
        if not target:
            return {"status": "error", "detail": spec.target_not_found}
        repo = session.get(Repository, target.repo_id)
        if not repo:
            return {"status": "error", "detail": "repository_not_found"}

        # The route creates one pending fix per (target, file). A file whose fix
        # is in any other state has no pending row and is skipped here.
        target_col = getattr(spec.fix_model, spec.target_id_field)
        fix = session.exec(
            select(spec.fix_model)
            .where(target_col == target.id)
            .where(spec.fix_model.file_path == file_path)
            .where(spec.fix_model.status == FixStatus.pending)
        ).first()
        if fix is None:
            return {"status": "skipped", "detail": "no_pending_fix"}

        sm.advance(fix, sm.FixMachine, "start_generation")
        session.add(fix)
        session.commit()
        session.refresh(fix)

        try:
            fetched = fetch_files(repo, target.root_path)
        except Exception as exc:
            logger.exception(
                "Failed to fetch %s files for fix %s: %s", spec.name, fix.id, exc
            )
            return _fail(session, fix, str(exc))

        source = next((f for f in fetched if f.path == file_path), None)
        if source is None:
            return _fail(session, fix, FILE_NOT_FOUND_ERROR)

        try:
            # Built before the event loop starts, not inside it. An engine's
            # `build_prompt` is synchronous, and the Docker one resolves
            # base-image digests from a registry — which it cannot do from
            # inside a running loop, since `asyncio.run` refuses to nest.
            # `_generate` called it first thing anyway, so this only moves the
            # call one frame out; a failure in either still fails the fix with
            # its own message.
            system_prompt, user_prompt = build_prompt(
                file_path, source.content, findings
            )
            result = asyncio.run(
                _generate(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    provider_str=fix.llm_provider.value,
                    model_str=fix.llm_model,
                )
            )
        except Exception as exc:
            logger.exception(
                "%s fix generation failed for %s: %s", spec.label, fix.id, exc
            )
            return _fail(session, fix, str(exc))

        full_content = parse_full_content(result.content)
        generation_error: str | None = None
        if not full_content:
            generation_error = MISSING_CONTENT_ERROR
        else:
            full_content = restore_trailing_whitespace(source.content, full_content)
            generation_error = validate(file_path, source.content, full_content)
            if generation_error:
                logger.warning(
                    "LLM full_content for %s does not re-parse; discarding", file_path
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
            # Parsed for parity with the workflow flow; neither engine's
            # findings carry a manual-work flag yet, so it's informational.
            parse_unfixed_issues(result.content)
        session.add(fix)
        session.commit()

        logger.info(
            "%s fix generation for %d finding(s) in %s: %s",
            spec.label,
            len(findings),
            file_path,
            fix.status.value,
        )
        return {"status": fix.status.value, "fix_id": str(fix.id)}


async def _generate(
    system_prompt: str,
    user_prompt: str,
    provider_str: str,
    model_str: str,
) -> LLMResponse:
    from app.services.llm.catalog import get_provider

    provider = get_provider(provider=provider_str, model=model_str)
    return await provider.generate(system_prompt, user_prompt)
