"""Deliver a scan target's ready fixes as one pull request.

Shared by the Terraform and Docker delivery tasks, which were previously the
same 227 lines twice over with the nouns swapped. Everything engine-specific
arrives via :class:`~app.services.engines.EngineSpec`; only ``fetch_files``
is passed separately, because each worker keeps its own module-level
``_fetch_*`` for the tests to patch.

One PR per target, one commit per file. The PR is reused across deliveries —
found by its deterministic branch name — so a second run updates the existing
pull request instead of opening a rival one.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis
from sqlmodel import Session, col, select

from app.core.config import settings
from app.core.db import engine
from app.models import PullRequest, PullRequestState, Repository
from app.models.enums import FixStatus
from app.services import state_machines as sm
from app.services.delivery_pr import record_pull_request
from app.services.engines import EngineSpec
from app.services.github.app_client import GitHubAppClient
from app.services.github.fix_delivery import FixDeliveryResult, FixDeliveryService

logger = logging.getLogger(__name__)

# Statuses a forced delivery will re-send. A normal delivery only picks up
# ``ready``; ``force`` additionally re-pushes what was already delivered and
# retries what failed, which is what the "Update PR" button does.
_FORCED_STATUSES = (FixStatus.ready, FixStatus.delivered, FixStatus.failed)


def _resolves_something(fix: Any) -> bool:
    """Whether this rewrite resolves any finding it was generated for.

    A generator that declines every finding it was given still returns a file,
    and that file is an edit nobody asked for. The workflow engine shipped one:
    it flipped `persist-credentials` on a workflow whose own comment said the
    action required it, under a commit subject that said no issues had been
    resolved. Withhold it here rather than push it.
    """
    open_findings = [f for f in fix.findings if f.resolved_at is None]
    if not open_findings:
        return True
    return any(not f.needs_manual_work for f in open_findings)


class FixFetchError(Exception):
    """Raised when the target's current files cannot be fetched from GitHub.

    Transient by nature (network, GitHub outage), so the calling Celery task
    turns it into a ``self.retry`` rather than failing the delivery outright.
    """


def _finding_line(finding: Any) -> str:
    slug = finding.rule.slug if finding.rule else "finding"
    return f"- **{slug}** ({finding.severity.value}): {finding.message}"


def build_pr_body(spec: EngineSpec, fixes: list[Any]) -> str:
    """The PR description: one section per file, listing what it fixes.

    A finding the generator reported under ``<unfixed>`` is listed separately
    rather than counted as fixed. Claiming one is worse than omitting it: the
    reviewer reads the table, sees the rule named, and assumes the diff below
    addresses it.
    """
    lines = [
        f"## {settings.PROJECT_NAME} {spec.label} fixes",
        "",
        f"This PR applies automated fixes to {spec.files_description} flagged "
        f"by {settings.PROJECT_NAME} static analysis.",
        "",
    ]
    manual: list[tuple[str, Any]] = []
    for fix in sorted(fixes, key=lambda f: f.file_path):
        lines.append(f"### `{fix.file_path}`")
        for finding in (f for f in fix.findings if f.resolved_at is None):
            if finding.needs_manual_work:
                manual.append((fix.file_path, finding))
                continue
            lines.append(_finding_line(finding))
        lines.append("")
    if manual:
        lines += [
            "---",
            "",
            "## Needs manual work",
            "",
            f"{len(manual)} finding{'s' if len(manual) != 1 else ''} "
            f"{'were' if len(manual) != 1 else 'was'} analysed but **not** "
            "changed by this PR — they need a judgement call this diff cannot "
            "make for you.",
            "",
        ]
        for path, finding in manual:
            note = (finding.manual_work_note or "").strip()
            lines.append(
                f"- `{path}` — {_finding_line(finding)[2:]}"
                + (f" _{note}_" if note else "")
            )
        lines.append("")
    return "\n".join(lines)


def deliver_file_fixes(
    spec: EngineSpec,
    target_id: str,
    force: bool,
    fetch_files: Callable[..., Any],
) -> dict[str, str]:
    """Deliver ``target_id``'s ready fixes as a single PR (one file change each).

    Raises :class:`FixFetchError` when GitHub cannot be reached, so the caller
    can retry; every other failure is recorded on the fix rows and returned.
    """
    with Session(engine) as session:
        target = session.get(spec.target_model, uuid.UUID(target_id))
        if not target:
            return {"status": "error", "detail": spec.target_not_found}
        repo = session.get(Repository, target.repo_id)
        if not repo:
            return {"status": "error", "detail": "repository_not_found"}

        # Delivery needs a GitHub App installation to push a branch.
        if repo.installation_id is None:
            logger.warning(
                "%s fix delivery skipped for repo %s: no installation",
                spec.label,
                repo.full_name,
            )
            return {"status": "skipped", "reason": "no_installation"}

        target_col = getattr(spec.fix_model, spec.target_id_field)
        status_col = spec.fix_model.status
        fixes = [
            fix
            for fix in session.exec(
                select(spec.fix_model)
                .where(target_col == target.id)
                .where(
                    col(status_col).in_(_FORCED_STATUSES)
                    if force
                    else status_col == FixStatus.ready
                )
            ).all()
            if fix.full_content and _resolves_something(fix)
        ]
        if not fixes:
            return {"status": "error", "detail": "no_ready_fixes"}

        pr_branch = spec.fix_branch(target.id)
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
                "Skipping %s delivery: PR on branch %s was closed",
                spec.name,
                pr_branch,
            )
            return {"status": "skipped", "reason": "pr_previously_closed"}

        # Fetch current base content for each delivered file so the delivery
        # service's staleness guard compares against fresh input (never a false
        # abort) and can revert files that dropped out of the set.
        try:
            fetched = fetch_files(repo, target.root_path)
        except Exception as exc:
            logger.exception(
                "Failed to fetch %s files for delivery: %s", spec.name, exc
            )
            raise FixFetchError(str(exc)) from exc
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
            # Only what this diff actually resolves — a finding the generator
            # reported under <unfixed> is in the PR body's "needs manual work"
            # section, and a commit claiming it would contradict the body
            # describing the same change. `_resolves_something` has already
            # withheld the fixes where that count would be zero.
            n = len(
                [
                    f
                    for f in fix.findings
                    if f.resolved_at is None and not f.needs_manual_work
                ]
            )
            commit_messages[fix.file_path] = (
                f"Fixing {n} finding{'s' if n != 1 else ''} in {fix.file_path}"
            )
        session.commit()

        result = asyncio.run(
            _deliver(
                installation_id=repo.installation_id,
                full_name=repo.full_name,
                base_branch=base_branch,
                fix_branch=pr_branch,
                file_changes=file_changes,
                pr_title=(
                    f"fix({spec.name}): apply {settings.PROJECT_NAME} fixes to "
                    f"{target.root_path or '/'}"
                ),
                pr_body=build_pr_body(spec, fixes),
                expected_base_contents=expected_base_contents,
                force=force,
                commit_messages=commit_messages,
            )
        )

        now = datetime.now(timezone.utc)
        pr: PullRequest | None = None
        if not result.error and result.pr_url:
            pr = record_pull_request(session, repo.id, pr_branch, result.pr_url)

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
