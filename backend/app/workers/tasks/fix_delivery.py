import asyncio
import logging
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.models import (
    Fix,
    FixDeliveryMode,
    FixStatus,
    PullRequest,
    PullRequestState,
    Repository,
)
from app.services import state_machines as sm
from app.services.events import publisher as events_pub
from app.services.events import schemas as ev
from app.services.github.fix_delivery import (
    STALE_CONTENT_ERROR_CODE,
    FixDeliveryResult,
    FixDeliveryService,
)
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

        # External repos have no GitHub App installation, so a branch cannot be
        # pushed to them directly. When a bot credential is configured we deliver
        # via a fork + cross-repo PR instead; otherwise there is nothing to do.
        external = repo.installation_id is None
        if external:
            if not (repo.is_external and settings.GITHUB_BOT_TOKEN):
                logger.warning(
                    "Fix delivery skipped for repo %s: no GitHub App installation "
                    "and no bot credential configured",
                    repo.full_name,
                )
                return {"status": "skipped", "reason": "no_bot_credential"}
            # Comment mode needs write access we don't have on an external repo;
            # outreach always goes out as a forked PR.
            delivery_mode = FixDeliveryMode.pr

        org_id = str(repo.org_id)
        repo_id_str = repo_id

        # `comment` mode surfaces the fixes on the base branch's HEAD commit
        # instead of opening a PR; it shares nothing with the PR branch flow.
        if delivery_mode == FixDeliveryMode.comment:
            return _deliver_batch_as_comment(
                session, repo, [f for f in fixes if f], org_id, repo_id_str
            )

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
                # This moves it to `superseded_by_closed_pr` — a distinct state
                # from a user rejection, so it can be restored on PR reopen.
                sm.advance(fix, sm.FixMachine, "supersede_closed_pr")
                # Link the fix to the PR that caused the rejection so the UI
                # can offer regeneration (regenerate-for-workflow/-repo) for it.
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
                if force:
                    sm.force_to(fix, sm.FixMachine, FixStatus.failed)
                else:
                    sm.advance(fix, sm.FixMachine, "precheck_failed")
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
            deliverable.append(fix)
        session.commit()

        fixes = deliverable
        if not fixes:
            return {"status": "error", "detail": "no_workflow_files"}

        for fix in fixes:
            # `force` may deliver a fix that is not `ready`; bypass the guard.
            if force:
                sm.force_to(fix, sm.FixMachine, FixStatus.delivering)
            else:
                sm.advance(fix, sm.FixMachine, "start_delivery")
            session.add(fix)
        session.commit()
        events_pub.publish_event(
            ev.fix_delivering_batch(org_id, repo_id_str, [str(f.id) for f in fixes])
        )

        if external:
            result = asyncio.run(
                _deliver_batch_forked(
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
        else:
            assert repo.installation_id is not None
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
                # PR creation is initialisation, not a transition (doc §4).
                pr = PullRequest(
                    repo_id=repo.id,
                    pr_branch=pr_branch,
                    pr_url=result.pr_url,
                    pr_state=PullRequestState.open,
                )
                session.add(pr)
                session.flush()
            else:
                pr.pr_url = result.pr_url
                # A forced redelivery onto a closed PR reopens it; a normal
                # redelivery is the open self-loop; a draft PR stays draft
                # (both events no-op on it). Merged PRs never reach here.
                if not sm.try_advance(pr, sm.PullRequestMachine, "reopen"):
                    sm.try_advance(pr, sm.PullRequestMachine, "redeliver")
                pr.updated_at = now
                if force and pr.externally_modified:
                    # The user explicitly forced delivery over their own
                    # edits: lift the auto-redelivery block.
                    pr.externally_modified = False
                session.add(pr)
                session.flush()

        for fix in fixes:
            # Every fix reached here in `delivering`, so these transitions are
            # always legal (no force needed).
            if result.error:
                sm.advance(fix, sm.FixMachine, "delivery_failed")
                fix.error_message = result.error
            else:
                sm.advance(fix, sm.FixMachine, "delivery_succeeded")
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
async def _delivery_service() -> AsyncGenerator[FixDeliveryService, None]:
    import redis.asyncio as aioredis

    from app.core.config import settings
    from app.services.github.app_client import GitHubAppClient

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
) -> FixDeliveryResult:
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


async def _deliver_batch_forked(
    full_name: str,
    base_branch: str,
    fix_branch: str,
    file_changes: list[tuple[str, str]],
    pr_title: str,
    pr_body: str,
    expected_base_contents: dict[str, str] | None = None,
    force: bool = False,
    commit_messages: dict[str, str] | None = None,
) -> FixDeliveryResult:
    async with _delivery_service() as svc:
        return await svc.update_or_create_forked_pr(
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


def _build_comment_body(fixes: list[Fix]) -> str:
    """Markdown body for a comment-mode delivery: issues + proposed content."""
    from app.core.config import settings

    lines = [f"## {settings.PROJECT_NAME} suggested workflow fixes", ""]
    for fix in fixes:
        wf = fix.workflow_file
        path = wf.path if wf else "workflow"
        lines.append(f"### `{path}`")
        if fix.issues:
            lines.append("")
            lines.append("Issues addressed:")
            for issue in fix.issues:
                slug = issue.rule.slug if issue.rule else "issue"
                lines.append(f"- **{slug}** ({issue.severity.value}): {issue.message}")
        lines += [
            "",
            "<details><summary>Proposed content</summary>",
            "",
            "```yaml",
            (fix.full_content or "").rstrip(),
            "```",
            "",
            "</details>",
            "",
        ]
    return "\n".join(lines)


async def _post_comment(
    installation_id: int, full_name: str, base_branch: str, body: str
) -> FixDeliveryResult:
    async with _delivery_service() as svc:
        return await svc.post_fix_comment(
            installation_id=installation_id,
            full_name=full_name,
            base_branch=base_branch,
            body=body,
        )


def _deliver_batch_as_comment(
    session: Session,
    repo: Repository,
    fixes: list[Fix],
    org_id: str,
    repo_id_str: str,
) -> dict[str, str]:
    """Deliver ready fixes as a single commit comment on the base branch HEAD."""
    deliverable: list[Fix] = []
    seen: set[str] = set()
    for fix in fixes:
        wf = fix.workflow_file
        if not wf or wf.path in seen:
            continue
        if not fix.full_content:
            sm.advance(fix, sm.FixMachine, "precheck_failed")
            fix.error_message = "Fix has no generated workflow content"
            session.add(fix)
            events_pub.publish_event(
                ev.fix_delivery_failed(
                    org_id, repo_id_str, str(fix.id), fix.error_message
                )
            )
            continue
        seen.add(wf.path)
        deliverable.append(fix)
    session.commit()

    if not deliverable:
        return {"status": "error", "detail": "no_workflow_files"}

    for fix in deliverable:
        sm.advance(fix, sm.FixMachine, "start_delivery")
        session.add(fix)
    session.commit()
    events_pub.publish_event(
        ev.fix_delivering_batch(org_id, repo_id_str, [str(f.id) for f in deliverable])
    )

    base_branch = repo.default_branch or "main"
    # The caller only routes here after checking installation_id is set.
    assert repo.installation_id is not None
    result = asyncio.run(
        _post_comment(
            installation_id=repo.installation_id,
            full_name=repo.full_name,
            base_branch=base_branch,
            body=_build_comment_body(deliverable),
        )
    )

    now = datetime.now(timezone.utc)
    if result.error or not result.comment_url:
        error = result.error or "comment delivery returned no URL"
        for fix in deliverable:
            sm.advance(fix, sm.FixMachine, "delivery_failed")
            fix.error_message = error
            session.add(fix)
        session.commit()
        events_pub.publish_event(
            ev.fix_delivery_failed(
                org_id, repo_id_str, str(deliverable[0].id), error[:200]
            )
        )
        return {"status": "failed"}

    # Reuse a stable per-repo record to hold the comment URL (no PR branch).
    comment_branch = f"greensecops/comments-{str(repo.id)[:8]}"
    pr = session.exec(
        select(PullRequest).where(
            PullRequest.repo_id == repo.id,
            PullRequest.pr_branch == comment_branch,
        )
    ).first()
    if pr is None:
        pr = PullRequest(
            repo_id=repo.id,
            pr_branch=comment_branch,
            comment_url=result.comment_url,
        )
        session.add(pr)
        session.flush()
    else:
        pr.comment_url = result.comment_url
        pr.updated_at = now
        session.add(pr)
        session.flush()

    delivered_fix_ids: list[str] = []
    for fix in deliverable:
        sm.advance(fix, sm.FixMachine, "delivery_succeeded")
        fix.pr_id = pr.id
        fix.delivered_at = now
        session.add(fix)
        delivered_fix_ids.append(str(fix.id))
    session.commit()

    events_pub.publish_event(
        ev.fix_delivered_batch(
            org_id, repo_id_str, delivered_fix_ids, result.comment_url, comment_branch
        )
    )
    return {"status": "ok"}
