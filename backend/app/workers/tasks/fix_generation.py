import asyncio
import logging
import os
import uuid

from sqlmodel import Session

from app.core.db import engine
from app.models import Fix, FixStatus, Issue, LLMProvider, Repository, WorkflowFile
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="fix_generation.run", bind=True, max_retries=3)
def run_fix_generation(
    self: object,  # noqa: ARG001
    issue_id: str,
) -> dict[str, str]:
    with Session(engine) as session:
        issue = session.get(Issue, uuid.UUID(issue_id))
        if not issue:
            return {"status": "error", "detail": "issue_not_found"}

        analysis = issue.analysis
        if not analysis:
            return {"status": "error", "detail": "analysis_not_found"}

        wf_file = session.get(WorkflowFile, analysis.workflow_file_id)
        if not wf_file:
            return {"status": "error", "detail": "workflow_file_not_found"}

        repo = session.get(Repository, analysis.repo_id)
        if not repo:
            return {"status": "error", "detail": "repository_not_found"}

        rule = issue.rule

        # Determine LLM provider (repo → org → first available)
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

        # Create Fix record in generating state
        fix = Fix(
            issue_id=issue.id,
            llm_provider=LLMProvider(provider_str),
            llm_model=model_str or "gpt-4o-mini",
            status=FixStatus.generating,
        )
        session.add(fix)
        session.commit()
        session.refresh(fix)

        try:
            result = asyncio.run(
                _generate_fix(
                    workflow_content=wf_file.raw_content,
                    issue_message=issue.message,
                    rule_slug=rule.slug if rule else "unknown",
                    category=issue.category.value,
                    severity=issue.severity.value,
                    job_name=None,
                    provider_str=fix.llm_provider.value,
                    model_str=fix.llm_model,
                )
            )
        except Exception as exc:
            logger.exception("Fix generation failed for issue %s: %s", issue_id, exc)
            fix.status = FixStatus.failed
            fix.error_message = str(exc)[:2000]
            session.add(fix)
            session.commit()
            return {"status": "failed", "issue_id": issue_id}

        fix.diff = result.content
        fix.prompt_tokens = result.prompt_tokens
        fix.completion_tokens = result.completion_tokens
        fix.langsmith_run_id = result.run_id
        fix.status = FixStatus.ready
        session.add(fix)
        session.commit()

        logger.info(
            "Fix generated for issue %s: %d prompt tokens, %d completion tokens",
            issue_id,
            result.prompt_tokens,
            result.completion_tokens,
        )
        return {"status": "ready", "fix_id": str(fix.id), "issue_id": issue_id}


@celery_app.task(name="fix_generation.run_batch", bind=True, max_retries=3)
def run_batch_fix_generation(
    self: object,  # noqa: ARG001
    issue_ids: list[str],
) -> dict:
    """Single LLM call to fix all issues (expected: same analysis/workflow file)."""
    with Session(engine) as session:
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

        llm_provider = LLMProvider(provider_str)
        llm_model = model_str or "gpt-4o-mini"

        fixes = []
        for issue in issues:
            fix = Fix(
                issue_id=issue.id,
                llm_provider=llm_provider,
                llm_model=llm_model,
                status=FixStatus.generating,
            )
            session.add(fix)
            fixes.append(fix)
        session.commit()
        for fix in fixes:
            session.refresh(fix)

        try:
            result = asyncio.run(
                _generate_batch_fix(
                    workflow_content=wf_file.raw_content,
                    issues=issues,
                    provider_str=llm_provider.value,
                    model_str=llm_model,
                )
            )
        except Exception as exc:
            logger.exception("Batch fix generation failed: %s", exc)
            for fix in fixes:
                fix.status = FixStatus.failed
                fix.error_message = str(exc)[:2000]
                session.add(fix)
            session.commit()
            return {"status": "failed"}

        for fix in fixes:
            fix.diff = result.content
            fix.prompt_tokens = result.prompt_tokens
            fix.completion_tokens = result.completion_tokens
            fix.langsmith_run_id = result.run_id
            fix.status = FixStatus.ready
            session.add(fix)
        session.commit()

        logger.info(
            "Batch fix generated for %d issues: %d prompt tokens, %d completion tokens",
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


async def _generate_batch_fix(
    workflow_content: str,
    issues: list,
    provider_str: str,
    model_str: str,
) -> object:
    from app.core.config import settings

    if settings.LANGCHAIN_TRACING_V2 and settings.LANGCHAIN_API_KEY:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = settings.LANGCHAIN_API_KEY
        os.environ["LANGCHAIN_PROJECT"] = settings.LANGCHAIN_PROJECT

    from app.services.llm.catalog import get_provider
    from app.services.llm.fix_prompt import build_batch_fix_prompt

    provider = get_provider(provider=provider_str, model=model_str)
    system_prompt, user_prompt = build_batch_fix_prompt(
        workflow_content=workflow_content,
        issues=issues,
    )
    return await provider.generate(system_prompt, user_prompt)


async def _generate_fix(
    workflow_content: str,
    issue_message: str,
    rule_slug: str,
    category: str,
    severity: str,
    job_name: str | None,
    provider_str: str,
    model_str: str,
) -> object:
    # Configure LangSmith tracing via env vars (already set from settings)
    from app.core.config import settings

    if settings.LANGCHAIN_TRACING_V2 and settings.LANGCHAIN_API_KEY:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = settings.LANGCHAIN_API_KEY
        os.environ["LANGCHAIN_PROJECT"] = settings.LANGCHAIN_PROJECT

    from app.services.llm.catalog import get_provider
    from app.services.llm.fix_prompt import build_fix_prompt

    provider = get_provider(provider=provider_str, model=model_str)
    system_prompt, user_prompt = build_fix_prompt(
        workflow_content=workflow_content,
        issue_message=issue_message,
        rule_slug=rule_slug,
        category=category,
        severity=severity,
        job_name=job_name,
    )
    return await provider.generate(system_prompt, user_prompt)
