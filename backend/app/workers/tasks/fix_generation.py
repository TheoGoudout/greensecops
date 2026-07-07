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
from app.workers.patch_utils import (
    apply_patch,
    normalize_patch,
    restore_trailing_whitespace,
)

logger = logging.getLogger(__name__)


def _is_valid_workflow_yaml(content: str) -> bool:
    """True if ``content`` parses as a YAML mapping (a plausible workflow file)."""
    import yaml  # type: ignore[import-untyped]

    try:
        return isinstance(yaml.safe_load(content), dict)
    except yaml.YAMLError:
        return False


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
    batch_mode: bool = False,
) -> dict:
    """Single LLM call to generate fixes for one or more issues in the same workflow file."""
    with Session(engine) as session:
        context = _load_generation_context(session, issue_ids)
        if isinstance(context, dict):
            return context
        issues, wf_file, repo = context

        provider_str, model_str = _resolve_llm_provider(repo)
        llm_provider = LLMProvider(provider_str)

        # Skip issues that already have a fix (unique constraint: one Fix per Issue).
        # The API preserves delivered fixes when force=False; inserting again would
        # violate fix_issue_id_key. When force=True the API deletes all fixes first,
        # so this set will be empty.
        existing_fix_issue_ids = set(
            session.exec(
                select(Fix.issue_id).where(  # type: ignore[arg-type]
                    Fix.issue_id.in_([i.id for i in issues])  # type: ignore[attr-defined]
                )
            ).all()
        )
        issues = [i for i in issues if i.id not in existing_fix_issue_ids]
        if not issues:
            events_pub.publish_event(ev.fix_skipped(str(repo.org_id), str(repo.id)))
            return {"status": "skipped", "detail": "all_issues_have_existing_fixes"}

        org_id = str(repo.org_id)
        repo_id_str = str(repo.id)

        fixes = []
        for issue in issues:
            fix = Fix(
                issue_id=issue.id,
                llm_provider=llm_provider,
                llm_model=model_str,
                status=FixStatus.generating,
            )
            session.add(fix)
            fixes.append(fix)
        session.commit()
        for fix in fixes:
            session.refresh(fix)

        if not batch_mode:
            events_pub.publish_event(
                ev.fix_generating(
                    org_id,
                    repo_id_str,
                    fix_ids=[str(f.id) for f in fixes],
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
            for fix in fixes:
                fix.status = FixStatus.failed
                fix.error_message = str(exc)[:2000]
                session.add(fix)
                events_pub.publish_event(
                    ev.fix_generation_failed(
                        org_id, repo_id_str, str(fix.id), str(exc)[:200]
                    )
                )
            session.commit()
            return {"status": "failed", "issue_ids": issue_ids}

        full_content, patches = _parse_llm_response(result.content)
        patches = {fp: normalize_patch(diff) for fp, diff in patches.items()}

        if full_content:
            full_content = restore_trailing_whitespace(
                wf_file.raw_content, full_content
            )
            # Only trust the LLM's full rewrite if it is still valid workflow YAML;
            # otherwise a later batch delivery would push a corrupt file.
            if _is_valid_workflow_yaml(full_content):
                wf_file.last_full_content = full_content
                session.add(wf_file)
            else:
                logger.warning(
                    "LLM full_content for wf %s is not valid YAML; discarding",
                    wf_file.id,
                )
                full_content = ""

        ready_fixes: list[Fix] = []
        failed_fixes: list[Fix] = []
        for fix in fixes:
            issue = session.get(Issue, fix.issue_id)
            patch = (
                patches.get(issue.fingerprint) if issue and issue.fingerprint else None
            )
            # Validate the patch actually applies and yields valid YAML before
            # marking the fix ready. A patch that fails here is not deliverable.
            if patch is not None:
                patched = apply_patch(wf_file.raw_content, patch)
                if patched is None or not _is_valid_workflow_yaml(patched):
                    logger.warning(
                        "LLM patch for fix %s is invalid (does not apply or bad YAML)",
                        fix.id,
                    )
                    patch = None
            fix.patch = patch
            fix.prompt_tokens = result.prompt_tokens
            fix.completion_tokens = result.completion_tokens
            fix.langsmith_run_id = result.run_id
            # A fix with neither a working patch nor a valid full rewrite must
            # not be marked ready: delivery would push the unchanged file and
            # fail with an opaque GitHub 422.
            if patch is None and not full_content:
                fix.status = FixStatus.failed
                fix.error_message = "LLM produced no applicable, valid fix"
                failed_fixes.append(fix)
            else:
                fix.status = FixStatus.ready
                ready_fixes.append(fix)
            session.add(fix)
        session.commit()

        for fix in failed_fixes:
            events_pub.publish_event(
                ev.fix_generation_failed(
                    org_id, repo_id_str, str(fix.id), fix.error_message or "no patch"
                )
            )
        if batch_mode:
            if ready_fixes:
                events_pub.publish_event(
                    ev.fix_ready_batch(
                        org_id, repo_id_str, [str(f.id) for f in ready_fixes]
                    )
                )
        else:
            for fix in ready_fixes:
                events_pub.publish_event(
                    ev.fix_ready(org_id, repo_id_str, str(fix.id), str(fix.issue_id))
                )

        logger.info(
            "Fix generation for %d issue(s): %d ready, %d failed, "
            "%d prompt tokens, %d completion tokens",
            len(fixes),
            len(ready_fixes),
            len(failed_fixes),
            result.prompt_tokens,
            result.completion_tokens,
        )
        return {
            "status": "ready" if ready_fixes else "failed",
            "fix_count": len(ready_fixes),
            "failed_count": len(failed_fixes),
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
        }


def _parse_llm_response(content: str) -> tuple[str, dict[str, str]]:
    """Parse LLM XML-delimited response into (full_content, {fingerprint: diff})."""
    import re

    full_content_match = re.search(
        r"<full_content>\n?(.*?)\n?</full_content>", content, re.DOTALL
    )
    full_content = full_content_match.group(1) if full_content_match else ""

    patches = {
        m.group(1): m.group(2)
        for m in re.finditer(
            r'<fix fingerprint="([^"]+)">\n?(.*?)\n?</fix>', content, re.DOTALL
        )
    }

    if not full_content:
        logger.warning(
            "LLM response missing <full_content> block. First 500 chars: %r",
            content[:500],
        )
    logger.info(
        "Parsed LLM response: full_content=%d chars, %d patches",
        len(full_content),
        len(patches),
    )
    return full_content, patches


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
