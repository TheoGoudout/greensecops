import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.models import (
    PullRequest,
    PullRequestState,
    Repository,
    TerraformFix,
    TerraformRoot,
)
from app.models.enums import FixStatus
from app.services import state_machines as sm
from app.services.delivery_pr import tf_fix_branch
from app.services.github.fix_delivery import FixDeliveryResult, FixDeliveryService
from app.workers.celery_app import celery_app
from app.workers.tasks.terraform_analysis import _fetch_terraform_files

logger = logging.getLogger(__name__)


def _build_terraform_pr_body(fixes: list[TerraformFix]) -> str:
    lines = [
        f"## {settings.PROJECT_NAME} Terraform fixes",
        "",
        "This PR applies automated fixes to Terraform files flagged by "
        f"{settings.PROJECT_NAME} static analysis.",
        "",
    ]
    for fix in sorted(fixes, key=lambda f: f.file_path):
        lines.append(f"### `{fix.file_path}`")
        findings = [f for f in fix.findings if f.resolved_at is None]
        if findings:
            for finding in findings:
                slug = finding.rule.slug if finding.rule else "finding"
                lines.append(
                    f"- **{slug}** ({finding.severity.value}): {finding.message}"
                )
        lines.append("")
    return "\n".join(lines)


@celery_app.task(name="terraform_fix_delivery.deliver", bind=True, max_retries=3)
def deliver_terraform_fixes(
    self: Any,  # noqa: ANN401 — celery bound task instance
    terraform_root_id: str,
    force: bool = False,
) -> dict[str, str]:
    """Deliver a Terraform root's ready fixes as one PR (one file change each)."""
    with Session(engine) as session:
        root = session.get(TerraformRoot, uuid.UUID(terraform_root_id))
        if not root:
            return {"status": "error", "detail": "terraform_root_not_found"}
        repo = session.get(Repository, root.repo_id)
        if not repo:
            return {"status": "error", "detail": "repository_not_found"}

        # Terraform delivery needs a GitHub App installation to push a branch.
        if repo.installation_id is None:
            logger.warning(
                "Terraform fix delivery skipped for repo %s: no installation",
                repo.full_name,
            )
            return {"status": "skipped", "reason": "no_installation"}

        fixes = list(
            session.exec(
                select(TerraformFix)
                .where(TerraformFix.terraform_root_id == root.id)
                .where(
                    TerraformFix.status == FixStatus.ready
                    if not force
                    else TerraformFix.status.in_(  # type: ignore[attr-defined]
                        [FixStatus.ready, FixStatus.delivered, FixStatus.failed]
                    )
                )
            ).all()
        )
        fixes = [f for f in fixes if f.full_content]
        if not fixes:
            return {"status": "error", "detail": "no_ready_fixes"}

        pr_branch = tf_fix_branch(root.id)
        base_branch = repo.default_branch or "main"

        # A PR the user closed without merging is a rejection signal unless forced.
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
            logger.info(
                "Skipping terraform delivery: PR on branch %s was closed", pr_branch
            )
            return {"status": "skipped", "reason": "pr_previously_closed"}

        # Fetch current base content for each delivered file so the delivery
        # service's staleness guard compares against fresh input (never a false
        # abort) and can revert files that dropped out of the set.
        try:
            fetched = _fetch_terraform_files(repo, root.root_path)
        except Exception as exc:
            logger.exception("Failed to fetch terraform files for delivery: %s", exc)
            raise self.retry(exc=exc, countdown=30) from exc
        base_by_path = {f.path: f.content for f in fetched}

        file_changes: list[tuple[str, str]] = []
        expected_base_contents: dict[str, str] = {}
        commit_messages: dict[str, str] = {}
        for fix in fixes:
            if force:
                sm.force_to(fix, sm.FixMachine, FixStatus.delivering)
            else:
                sm.advance(fix, sm.FixMachine, "start_delivery")
            session.add(fix)
            file_changes.append((fix.file_path, fix.full_content or ""))
            if fix.file_path in base_by_path:
                expected_base_contents[fix.file_path] = base_by_path[fix.file_path]
            n = len([f for f in fix.findings if f.resolved_at is None])
            commit_messages[fix.file_path] = (
                f"Fixing {n} finding{'s' if n != 1 else ''} in {fix.file_path}"
            )
        session.commit()

        pr_title = f"fix(terraform): apply {settings.PROJECT_NAME} fixes to {root.root_path}"
        pr_body = _build_terraform_pr_body(fixes)

        result = asyncio.run(
            _deliver(
                installation_id=repo.installation_id,
                full_name=repo.full_name,
                base_branch=base_branch,
                fix_branch=pr_branch,
                file_changes=file_changes,
                pr_title=pr_title,
                pr_body=pr_body,
                expected_base_contents=expected_base_contents,
                force=force,
                commit_messages=commit_messages,
            )
        )

        now = datetime.now(timezone.utc)
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
                    pr_state=PullRequestState.open,
                )
                session.add(pr)
                session.flush()
            else:
                pr.pr_url = result.pr_url
                if not sm.try_advance(pr, sm.PullRequestMachine, "reopen"):
                    sm.try_advance(pr, sm.PullRequestMachine, "redeliver")
                pr.updated_at = now
                session.add(pr)
                session.flush()

        for fix in fixes:
            if result.error:
                sm.advance(fix, sm.FixMachine, "delivery_failed")
                fix.error_message = result.error[:2000]
            else:
                sm.advance(fix, sm.FixMachine, "delivery_succeeded")
                fix.pr_id = pr.id if pr else None
                fix.delivered_at = now
            session.add(fix)
        session.commit()

        return {"status": "failed" if result.error else "ok"}


async def _deliver(
    installation_id: int,
    full_name: str,
    base_branch: str,
    fix_branch: str,
    file_changes: list[tuple[str, str]],
    pr_title: str,
    pr_body: str,
    expected_base_contents: dict[str, str],
    force: bool,
    commit_messages: dict[str, str],
) -> FixDeliveryResult:
    import redis.asyncio as aioredis

    from app.services.github.app_client import GitHubAppClient

    r = aioredis.from_url(settings.REDIS_URL)  # type: ignore[no-untyped-call]
    try:
        svc = FixDeliveryService(app_client=GitHubAppClient(redis_client=r))
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
    finally:
        await r.aclose()
