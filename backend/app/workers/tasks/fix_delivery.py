import asyncio
import logging
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from app.models import (
    Fix,
    FixDeliveryMode,
    FixStatus,
    Repository,
    WorkflowFile,
)
from app.services.events import publisher as events_pub
from app.services.events import schemas as ev
from app.services.pr_body import IssueInfo, build_pr_body
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="fix_delivery.deliver", bind=True, max_retries=3)
def deliver_fix(
    self: object,  # noqa: ARG001
    fix_id: str,
    force: bool = False,
) -> dict[str, str]:
    with Session(engine) as session:
        fix = session.get(Fix, uuid.UUID(fix_id))
        if not fix:
            return {"status": "error", "detail": "fix_not_found"}
        if not force and fix.status != FixStatus.ready:
            return {"status": "error", "detail": f"fix_not_ready: {fix.status}"}

        issue = fix.issue
        if not issue:
            return {"status": "error", "detail": "issue_not_found"}

        analysis = issue.analysis
        repo = session.get(Repository, analysis.repo_id) if analysis else None
        if not repo:
            return {"status": "error", "detail": "repository_not_found"}

        wf_file = (
            session.get(WorkflowFile, analysis.workflow_file_id) if analysis else None
        )
        if not wf_file:
            return {"status": "error", "detail": "workflow_file_not_found"}

        # Determine delivery mode (repo → org → pr)
        delivery_mode = (
            repo.fix_delivery_mode
            or (repo.organization.fix_delivery_mode if repo.organization else None)
            or FixDeliveryMode.pr
        )

        if delivery_mode == FixDeliveryMode.disabled:
            logger.info("Fix delivery disabled for repo %s", repo.full_name)
            return {"status": "skipped", "reason": "delivery_disabled"}

        if repo.installation_id is None:
            logger.warning(
                "Fix delivery skipped for external repo %s: no GitHub App installation",
                repo.full_name,
            )
            return {"status": "skipped", "reason": "no_installation"}

        org_id = str(repo.org_id)
        repo_id_str = str(repo.id)

        fix.status = FixStatus.delivering
        session.add(fix)
        session.commit()
        events_pub.publish_event(ev.fix_delivering(org_id, repo_id_str, fix_id))

        rule = issue.rule
        pr_body = build_pr_body(
            issues=[
                IssueInfo(
                    rule_slug=rule.slug if rule else "fix",
                    rule_title=rule.title if rule else "fix",
                    category=issue.category.value if issue.category else "unknown",
                    severity=issue.severity.value if issue.severity else "unknown",
                    message=issue.message or "",
                )
            ],
            fix_ids=[fix_id],
            wiki_base_url=settings.WIKI_BASE_URL,
            frontend_host=settings.FRONTEND_HOST,
            bot_handle=settings.GITHUB_BOT_HANDLE,
        )

        rule_slug = issue.rule.slug if issue.rule else "fix"
        fix_branch = fix.pr_branch or f"greensecops/fix-{rule_slug}-{str(wf_file.id)[:8]}"
        result = asyncio.run(
            _deliver(
                installation_id=repo.installation_id,
                full_name=repo.full_name,
                base_branch=analysis.branch or repo.default_branch,
                file_path=wf_file.path,
                new_content=fix.diff or wf_file.raw_content,
                fix_branch=fix_branch,
                rule_slug=rule_slug,
                delivery_mode=delivery_mode.value,
                pr_body=pr_body,
            )
        )

        if result.error:
            fix.status = FixStatus.failed
            fix.error_message = result.error
            session.add(fix)
            session.commit()
            events_pub.publish_event(
                ev.fix_delivery_failed(org_id, repo_id_str, fix_id, result.error[:200])
            )
        else:
            fix.status = FixStatus.delivered
            fix.pr_url = result.pr_url
            fix.pr_branch = fix_branch
            fix.pr_state = "open" if result.pr_url else None
            fix.comment_url = result.comment_url
            fix.delivered_at = datetime.now(timezone.utc)
            session.add(fix)
            session.commit()
            events_pub.publish_event(
                ev.fix_delivered(org_id, repo_id_str, fix_id, result.pr_url, fix_branch)
            )
            if result.pr_url:
                events_pub.publish_event(
                    ev.pr_opened(
                        org_id, repo_id_str, [fix_id], result.pr_url, fix_branch
                    )
                )

        return {"status": fix.status.value, "fix_id": fix_id}


@celery_app.task(name="fix_delivery.deliver_batch", bind=True, max_retries=3)
def deliver_fixes_batch(
    self: object,  # noqa: ARG001
    fix_ids: list[str],
    repo_id: str,
    pr_branch: str,
    pr_title: str,
    pr_body: str,
    force: bool = False,
) -> dict[str, str]:
    """Deliver multiple ready fixes as a single PR (one file change per workflow file)."""
    with Session(engine) as session:
        repo = session.get(Repository, uuid.UUID(repo_id))
        if not repo:
            return {"status": "error", "detail": "repository_not_found"}

        fixes = [session.get(Fix, uuid.UUID(fid)) for fid in fix_ids]
        fixes = [f for f in fixes if f and (force or f.status == FixStatus.ready)]
        if not fixes:
            return {"status": "error", "detail": "no_ready_fixes"}

        # One file change per workflow file — all fixes for same file share identical diff
        seen: dict[str, tuple[str, str]] = {}
        base_branch = repo.default_branch or "main"
        for fix in fixes:
            issue = fix.issue
            if not issue:
                continue
            analysis = issue.analysis
            if not analysis:
                continue
            wf = session.get(WorkflowFile, analysis.workflow_file_id)
            if not wf or wf.path in seen:
                continue
            seen[wf.path] = (wf.path, fix.diff or wf.raw_content)
            base_branch = analysis.branch or repo.default_branch or "main"

        if not seen:
            return {"status": "error", "detail": "no_workflow_files"}

        org_id = str(repo.org_id)
        repo_id_str = repo_id

        for fix in fixes:
            fix.status = FixStatus.delivering
            session.add(fix)
        session.commit()
        for fix in fixes:
            events_pub.publish_event(
                ev.fix_delivering(org_id, repo_id_str, str(fix.id))
            )

        result = asyncio.run(
            _deliver_batch(
                installation_id=repo.installation_id,
                full_name=repo.full_name,
                base_branch=base_branch,
                fix_branch=pr_branch,
                file_changes=list(seen.values()),
                pr_title=pr_title,
                pr_body=pr_body,
            )
        )

        now = datetime.now(timezone.utc)
        delivered_fix_ids = []
        for fix in fixes:
            if result.error:
                fix.status = FixStatus.failed
                fix.error_message = result.error
            else:
                fix.status = FixStatus.delivered
                fix.pr_url = result.pr_url
                fix.pr_branch = pr_branch
                fix.pr_state = "open" if result.pr_url else None
                fix.delivered_at = now
                delivered_fix_ids.append(str(fix.id))
            session.add(fix)
        session.commit()

        if result.error:
            for fix in fixes:
                events_pub.publish_event(
                    ev.fix_delivery_failed(
                        org_id, repo_id_str, str(fix.id), result.error[:200]
                    )
                )
        else:
            for fix in fixes:
                events_pub.publish_event(
                    ev.fix_delivered(
                        org_id, repo_id_str, str(fix.id), result.pr_url, pr_branch
                    )
                )
            if result.pr_url and delivered_fix_ids:
                events_pub.publish_event(
                    ev.pr_opened(
                        org_id, repo_id_str, delivered_fix_ids, result.pr_url, pr_branch
                    )
                )

        return {"status": "failed" if result.error else "ok"}


@asynccontextmanager
async def _delivery_service() -> AsyncGenerator[object, None]:
    import redis.asyncio as aioredis

    from app.core.config import settings
    from app.services.github.app_client import GitHubAppClient
    from app.services.github.fix_delivery import FixDeliveryService

    r = aioredis.from_url(settings.REDIS_URL)
    try:
        yield FixDeliveryService(app_client=GitHubAppClient(redis_client=r))
    finally:
        await r.aclose()


async def _deliver_batch(
    installation_id: int,
    full_name: str,
    base_branch: str,
    fix_branch: str,
    file_changes: list[tuple[str, str]],
    pr_title: str,
    pr_body: str,
) -> object:
    async with _delivery_service() as svc:
        return await svc.update_or_create_workflow_action_pr(
            installation_id=installation_id,
            full_name=full_name,
            base_branch=base_branch,
            fix_branch=fix_branch,
            file_changes=file_changes,
            pr_title=pr_title,
            pr_body=pr_body,
        )


async def _deliver(
    installation_id: int,
    full_name: str,
    base_branch: str,
    file_path: str,
    new_content: str,
    fix_branch: str,
    rule_slug: str,
    delivery_mode: str,
    pr_body: str,
) -> object:
    async with _delivery_service() as svc:
        if delivery_mode == "pr":
            return await svc.update_or_create_pr(
                installation_id=installation_id,
                full_name=full_name,
                base_branch=base_branch,
                fix_branch=fix_branch,
                file_path=file_path,
                new_content=new_content,
                pr_title=f"fix(ci): {rule_slug.replace('_', ' ')}",
                pr_body=pr_body,
            )
        return await svc.deliver_as_comment(
            installation_id=installation_id,
            full_name=full_name,
            issue_number=1,
            body=f"**GreenSecOps Fix** for `{rule_slug}`:\n\n```yaml\n{new_content}\n```",
        )
