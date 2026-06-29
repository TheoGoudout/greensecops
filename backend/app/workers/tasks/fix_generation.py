import asyncio
import json
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

        for fix in fixes:
            issue = session.get(Issue, fix.issue_id)
            fix.diff = full_content or result.content
            fix.patch = (
                patches.get(issue.fingerprint) if issue and issue.fingerprint else None
            )
            fix.prompt_tokens = result.prompt_tokens
            fix.completion_tokens = result.completion_tokens
            fix.langsmith_run_id = result.run_id
            fix.status = FixStatus.ready
            session.add(fix)
        session.commit()

        for fix in fixes:
            events_pub.publish_event(
                ev.fix_ready(org_id, repo_id_str, str(fix.id), str(fix.issue_id))
            )

        logger.info(
            "Fix generated for %d issue(s): %d prompt tokens, %d completion tokens",
            len(fixes),
            result.prompt_tokens,
            result.completion_tokens,
        )
        return {
            "status": "ready",
            "fix_count": len(fixes),
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
        }


def _parse_llm_response(content: str) -> tuple[str, dict[str, str]]:
    """Parse LLM JSON response into (full_content, {fingerprint: diff}).

    Falls back to treating full content as the diff when JSON is invalid.
    """
    try:
        data = json.loads(content)
        full_content = data.get("full_content") or ""
        patches = {
            item["fingerprint"]: item["diff"]
            for item in data.get("fixes", [])
            if "fingerprint" in item and "diff" in item
        }
        return full_content, patches
    except (json.JSONDecodeError, TypeError, AttributeError):
        return content, {}


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

    from app.services.github.sha_resolver import resolve_action_shas
    from app.services.llm.catalog import get_provider
    from app.services.llm.fix_prompt import build_fix_prompt

    action_sha_map = await resolve_action_shas(workflow_content)
    provider = get_provider(provider=provider_str, model=model_str)
    system_prompt, user_prompt = build_fix_prompt(
        workflow_content=workflow_content,
        issues=issues,
        action_sha_map=action_sha_map or None,
    )
    return await provider.generate(system_prompt, user_prompt)
