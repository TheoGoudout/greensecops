import asyncio
import logging
import os
import uuid

from sqlmodel import Session, select

from app.core.db import engine
from app.models import Fix, FixStatus, Issue, LLMProvider, Repository, WorkflowFile
from app.services.events import publisher as events_pub
from app.services.events import schemas as ev
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _is_valid_workflow_yaml(content: str) -> bool:
    """True if ``content`` parses as a YAML mapping (a plausible workflow file)."""
    import yaml  # type: ignore[import-untyped]

    try:
        return isinstance(yaml.safe_load(content), dict)
    except yaml.YAMLError:
        return False


def restore_trailing_whitespace(original: str, patched: str) -> str:
    """Restore original trailing whitespace on lines that only differ in trailing whitespace.

    LLMs routinely strip trailing whitespace when regenerating file content.
    For lines where the stripped versions are identical, keep the original so
    the delivered diff contains only meaningful changes.
    """
    orig_lines = original.split("\n")
    new_lines = patched.split("\n")
    result = []
    for i, new_line in enumerate(new_lines):
        if (
            i < len(orig_lines)
            and new_line.rstrip() == orig_lines[i].rstrip()
            and new_line != orig_lines[i]
        ):
            result.append(orig_lines[i])
        else:
            result.append(new_line)
    return "\n".join(result)


def _resolve_llm_provider(repo: Repository) -> tuple[str, str]:
    """Return (provider_str, model_str), cascading repo → org → first available."""
    provider_str = repo.llm_provider.value if repo.llm_provider else None
    model_str = repo.llm_model

    if not provider_str and repo.organization:
        org = repo.organization
        provider_str = (
            org.default_llm_provider.value if org.default_llm_provider else None
        )
        model_str = model_str or org.default_llm_model

    if not provider_str:
        from app.services.llm.catalog import get_first_available_provider

        provider_str, fallback_model = get_first_available_provider()
        model_str = model_str or fallback_model

    if not model_str:
        # Use the provider's own catalog default — an OpenAI model name
        # handed to anthropic/gemini/ollama would fail at request time.
        from app.services.llm.catalog import get_default_model

        model_str = get_default_model(provider_str)

    return provider_str, model_str or "gpt-4o-mini"


def _load_generation_context(
    session: Session,
    issue_ids: list[str],
) -> tuple[list[Issue], WorkflowFile, Repository] | dict:
    """Load and validate issues, workflow file, and repo. Returns error dict on failure."""
    issues = [session.get(Issue, uuid.UUID(iid)) for iid in issue_ids]
    issues = [i for i in issues if i is not None]
    if not issues:
        return {"status": "error", "detail": "no_issues_found"}

    analysis = issues[0].analysis
    if not analysis:
        return {"status": "error", "detail": "analysis_not_found"}

    wf_file = session.get(WorkflowFile, analysis.workflow_file_id)
    if not wf_file:
        return {"status": "error", "detail": "workflow_file_not_found"}

    repo = session.get(Repository, analysis.repo_id)
    if not repo:
        return {"status": "error", "detail": "repository_not_found"}

    return issues, wf_file, repo


@celery_app.task(name="fix_generation.run", bind=True, max_retries=3)
def run_fix_generation(
    self: object,  # noqa: ARG001
    issue_ids: list[str],
    batch_mode: bool = False,  # noqa: ARG001 — kept for queued-task compatibility
) -> dict:
    """Single LLM call regenerating one workflow file to fix the given issues."""
    with Session(engine) as session:
        context = _load_generation_context(session, issue_ids)
        if isinstance(context, dict):
            return context
        issues, wf_file, repo = context

        provider_str, model_str = _resolve_llm_provider(repo)
        llm_provider = LLMProvider(provider_str)

        # One Fix per workflow file (unique constraint). The API preserves
        # delivered fixes when force=False; inserting again would violate
        # fix_workflow_file_id_key. When force=True the API deletes the
        # existing fix first, so this lookup comes back empty.
        existing_fix = session.exec(
            select(Fix).where(Fix.workflow_file_id == wf_file.id)
        ).first()
        if existing_fix is not None:
            events_pub.publish_event(ev.fix_skipped(str(repo.org_id), str(repo.id)))
            return {"status": "skipped", "detail": "workflow_file_has_existing_fix"}

        org_id = str(repo.org_id)
        repo_id_str = str(repo.id)

        fix = Fix(
            workflow_file_id=wf_file.id,
            llm_provider=llm_provider,
            llm_model=model_str,
            status=FixStatus.generating,
        )
        session.add(fix)
        for issue in issues:
            issue.fix_id = fix.id
            session.add(issue)
        session.commit()
        session.refresh(fix)

        events_pub.publish_event(
            ev.fix_generating(
                org_id,
                repo_id_str,
                fix_ids=[str(fix.id)],
                issue_ids=issue_ids,
            )
        )

        try:
            result = asyncio.run(
                _generate_fixes(
                    workflow_content=wf_file.raw_content,
                    issues=issues,
                    provider_str=llm_provider.value,
                    model_str=model_str,
                )
            )
        except Exception as exc:
            logger.exception("Fix generation failed for issues %s: %s", issue_ids, exc)
            fix.status = FixStatus.failed
            fix.error_message = str(exc)[:2000]
            session.add(fix)
            session.commit()
            events_pub.publish_event(
                ev.fix_generation_failed(
                    org_id, repo_id_str, str(fix.id), str(exc)[:200]
                )
            )
            return {"status": "failed", "issue_ids": issue_ids}

        full_content = _parse_llm_response(result.content)

        if full_content:
            full_content = restore_trailing_whitespace(
                wf_file.raw_content, full_content
            )
            # Only trust the LLM's rewrite if it is still valid workflow YAML;
            # otherwise delivery would push a corrupt file.
            if not _is_valid_workflow_yaml(full_content):
                logger.warning(
                    "LLM full_content for wf %s is not valid YAML; discarding",
                    wf_file.id,
                )
                full_content = ""

        fix.prompt_tokens = result.prompt_tokens
        fix.completion_tokens = result.completion_tokens
        fix.langsmith_run_id = result.run_id
        if not full_content:
            fix.status = FixStatus.failed
            fix.error_message = "LLM produced no valid full workflow content"
        else:
            fix.full_content = full_content
            fix.status = FixStatus.ready
        session.add(fix)
        session.commit()

        if fix.status == FixStatus.failed:
            events_pub.publish_event(
                ev.fix_generation_failed(
                    org_id, repo_id_str, str(fix.id), fix.error_message or "no fix"
                )
            )
        else:
            events_pub.publish_event(
                ev.fix_ready(org_id, repo_id_str, str(fix.id), issue_ids)
            )

        logger.info(
            "Fix generation for %d issue(s) in %s: %s, "
            "%d prompt tokens, %d completion tokens",
            len(issues),
            wf_file.path,
            fix.status.value,
            result.prompt_tokens,
            result.completion_tokens,
        )
        return {
            "status": fix.status.value,
            "fix_id": str(fix.id),
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
        }


def _parse_llm_response(content: str) -> str:
    """Extract the full regenerated workflow from the LLM's XML-delimited response."""
    import re

    full_content_match = re.search(
        r"<full_content>\n?(.*?)\n?</full_content>", content, re.DOTALL
    )
    full_content = full_content_match.group(1) if full_content_match else ""

    if not full_content:
        logger.warning(
            "LLM response missing <full_content> block. First 500 chars: %r",
            content[:500],
        )
    logger.info("Parsed LLM response: full_content=%d chars", len(full_content))
    return full_content


def _configure_langchain() -> None:
    from app.core.config import settings

    if settings.LANGCHAIN_TRACING_V2 and settings.LANGCHAIN_API_KEY:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = settings.LANGCHAIN_API_KEY
        os.environ["LANGCHAIN_PROJECT"] = settings.LANGCHAIN_PROJECT
        os.environ["LANGCHAIN_ENDPOINT"] = settings.LANGCHAIN_ENDPOINT


async def _generate_fixes(
    workflow_content: str,
    issues: list,
    provider_str: str,
    model_str: str,
) -> object:
    _configure_langchain()

    from app.services.github.sha_resolver import resolve_action_shas, resolve_extra_shas
    from app.services.llm.catalog import get_provider
    from app.services.llm.fix_prompt import build_fix_prompt

    action_sha_map = await resolve_action_shas(workflow_content)
    action_sha_map = await resolve_extra_shas(action_sha_map)
    provider = get_provider(provider=provider_str, model=model_str)
    system_prompt, user_prompt = build_fix_prompt(
        workflow_content=workflow_content,
        issues=issues,
        action_sha_map=action_sha_map or None,
    )
    return await provider.generate(system_prompt, user_prompt)
