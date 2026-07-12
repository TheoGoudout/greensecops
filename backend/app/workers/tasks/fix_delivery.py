import asyncio
import logging
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.core.db import engine
from app.models import (
    Fix,
    FixDeliveryMode,
    FixStatus,
    PullRequest,
    PullRequestState,
    Repository,
)
from app.services.events import publisher as events_pub
from app.services.events import schemas as ev
from app.services.github.fix_delivery import STALE_CONTENT_ERROR_CODE
from app.services.state_machines import FixEvent, fix_machine
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


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
    """Deliver ready workflow fixes as a single PR (one file change per workflow file)."""
    with Session(engine) as session:
        repo = session.get(Repository, uuid.UUID(repo_id))
        if not repo:
            return {"status": "error", "detail": "repository_not_found"}

        fixes = [session.get(Fix, uuid.UUID(fid)) for fid in fix_ids]
        fixes = [f for f in fixes if f and (force or f.status == FixStatus.ready)]
        if not fixes:
            return {"status": "error", "detail": "no_ready_fixes"}

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
        repo_id_str = repo_id

        # A PR the user closed without merging is a rejection signal: do not
        # re-open it on the next delivery unless explicitly forced.
        branch_pr = session.exec(
            select(PullRequest).where(
                PullRequest.repo_id == repo.id,
                PullRequest.pr_branch == pr_branch,
            )
        ).first()
        if (
            not force
            and branch_pr is not None
            and branch_pr.pr_state == PullRequestState.closed
        ):
            for fix in fixes:
                # Guard runs only when not forced, so every fix here is `ready`.
                fix_machine.trigger(fix, FixEvent.supersede_closed_pr)
                # Link the fix to the PR that caused the rejection so the UI
                # can offer regeneration (regenerate-for-workflow/-repo) for
                # it. A guard rejection is recognizable later by delivered_at
                # being unset.
                fix.pr_id = branch_pr.id
                session.add(fix)
            session.commit()
            events_pub.publish_event(
                ev.fix_rejected(org_id, repo_id_str, str(fixes[0].id))
            )
            logger.info(
                "Skipping batch delivery: PR on branch %s was closed by user",
                pr_branch,
            )
            return {"status": "skipped", "reason": "pr_previously_closed"}

        # One file change per workflow fix. A fix without generated content is
        # not deliverable: pushing the unchanged file would fail with an
        # opaque GitHub 422.
        seen: dict[str, tuple[str, str]] = {}
        expected_base_contents: dict[str, str] = {}
        commit_messages: dict[str, str] = {}
        base_branch = repo.default_branch or "main"
        deliverable: list[Fix] = []
        for fix in fixes:
            wf = fix.workflow_file
            if not wf or wf.path in seen:
                continue
            if not fix.full_content:
                # `force` can bring a non-ready fix here; bypass the source check.
                fix_machine.apply(fix, FixEvent.precheck_failed, force=force)
                fix.error_message = "Fix has no generated workflow content"
                session.add(fix)
                events_pub.publish_event(
                    ev.fix_delivery_failed(
                        org_id, repo_id_str, str(fix.id), fix.error_message
                    )
                )
                continue
            seen[wf.path] = (wf.path, fix.full_content)
            expected_base_contents[wf.path] = wf.raw_content
            n_issues = len(fix.issues)
            commit_messages[wf.path] = (
                f"Fixing {n_issues} issue{'s' if n_issues != 1 else ''} in {wf.path}"
            )
            issue = fix.issues[0] if fix.issues else None
            analysis = issue.analysis if issue else None
            base_branch = (
                (analysis.branch if analysis else None) or repo.default_branch or "main"
            )
            deliverable.append(fix)
        session.commit()

        fixes = deliverable
        if not fixes:
            return {"status": "error", "detail": "no_workflow_files"}

        for fix in fixes:
            # `force` may deliver a fix that is not `ready`; bypass the guard.
            fix_machine.apply(fix, FixEvent.start_delivery, force=force)
            session.add(fix)
        session.commit()
        events_pub.publish_event(
            ev.fix_delivering_batch(org_id, repo_id_str, [str(f.id) for f in fixes])
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
                expected_base_contents=expected_base_contents,
                force=force,
                commit_messages=commit_messages,
            )
        )

        now = datetime.now(timezone.utc)
        delivered_fix_ids = []
        pr: PullRequest | None = None
        if not result.error and result.pr_url:
            pr = session.exec(
                select(PullRequest).where(
                    PullRequest.repo_id == repo.id,
                    PullRequest.pr_branch == pr_branch,
                )
            ).first()
            if pr is None:
                pr = PullRequest(
                    repo_id=repo.id,
                    pr_branch=pr_branch,
                    pr_url=result.pr_url,
                    pr_state="open",
                )
                session.add(pr)
                session.flush()
            else:
                pr.pr_url = result.pr_url
                pr.pr_state = "open"
                pr.updated_at = now
                session.add(pr)
                session.flush()

        for fix in fixes:
            # Every fix reached here in `delivering`, so these transitions are
            # always legal (no force needed).
            if result.error:
                fix_machine.trigger(fix, FixEvent.delivery_failed)
                fix.error_message = result.error
            else:
                fix_machine.trigger(fix, FixEvent.delivery_succeeded)
                fix.pr_id = pr.id if pr else None
                fix.delivered_at = now
                delivered_fix_ids.append(str(fix.id))
            session.add(fix)
        session.commit()

        if result.error:
            events_pub.publish_event(
                ev.fix_delivery_failed(
                    org_id,
                    repo_id_str,
                    fix_ids[0] if fix_ids else "",
                    result.error[:200],
                )
            )
            if result.error_code == STALE_CONTENT_ERROR_CODE:
                from app.workers.tasks.static_analysis import run_static_analysis

                run_static_analysis.delay(
                    repo_id=repo_id_str,
                    branch=base_branch,
                    trigger="manual",
                    force=True,
                )
        else:
            events_pub.publish_event(
                ev.fix_delivered_batch(
                    org_id, repo_id_str, delivered_fix_ids, result.pr_url, pr_branch
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
    expected_base_contents: dict[str, str] | None = None,
    force: bool = False,
    commit_messages: dict[str, str] | None = None,
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
            expected_base_contents=expected_base_contents,
            override_user_commits=force,
            commit_messages=commit_messages,
        )
