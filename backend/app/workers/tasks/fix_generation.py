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
def run_fix_generation(self: object, issue_id: str) -> dict[str, str]:
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

        # Determine LLM provider (repo → org → global default)
        provider_str = (
            repo.llm_provider.value if repo.llm_provider else None
        )
        model_str = repo.llm_model

        if not provider_str and repo.organization:
            org = repo.organization
            provider_str = org.default_llm_provider.value if org.default_llm_provider else None
            model_str = model_str or org.default_llm_model

        # Create Fix record in generating state
        fix = Fix(
            issue_id=issue.id,
            llm_provider=LLMProvider(provider_str) if provider_str else LLMProvider.openai,
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
            issue_id, result.prompt_tokens, result.completion_tokens,
        )
        return {"status": "ready", "fix_id": str(fix.id), "issue_id": issue_id}


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
