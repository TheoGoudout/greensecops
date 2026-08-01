"""External-repo polling — the webhook analogue for repos we can't webhook.

External repos (`Repository.is_external`, no App installation) receive no GitHub
webhooks, so their state is reconciled by periodically fetching the REST API.
This module is only the **source**: it turns REST snapshots into the same
normalized inputs a webhook would, then hands them to the shared
`app.services.github.event_handlers`. All the actual state transitions, fix
landing, issue resolution and SSE live there, so an external repo and a webhook
repo are handled by identical code.

The same poll doubles as a missed-webhook safety net for installation repos
(``external_only=False``), replacing the old bespoke
``maintenance.sync_open_pr_states``.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlmodel import Session, col, select

from app.core.db import engine
from app.models import (
    AnalysisTrigger,
    PullRequest,
    PullRequestState,
    Repository,
)
from app.services.github import event_handlers as eh
from app.services.github.app_client import PRSnapshot, parse_pr_url
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# Space out per-repo poll tasks so a large fleet doesn't hammer GitHub at once
# (mirrors static_analysis.REANALYZE_STAGGER_SECONDS).
POLL_STAGGER_SECONDS = 5


@dataclass
class _PRPollResult:
    snapshot: PRSnapshot | None
    command_comments: list[str]


@dataclass
class _RepoPollData:
    branch: str | None
    head_sha: str | None
    prs: dict[uuid.UUID, _PRPollResult]


async def _fetch_repo_poll_data(
    repo: Repository, prs: list[PullRequest]
) -> _RepoPollData:
    """Fetch the default-branch head and a snapshot per open PR from GitHub.

    Per-item failures are swallowed (logged) so one unreachable PR or a repo we
    lack credentials for never sinks the whole poll.
    """
    import redis.asyncio as aioredis

    from app.core.config import settings
    from app.services.github.app_client import GitHubAppClient

    r = aioredis.from_url(settings.REDIS_URL)  # type: ignore[no-untyped-call]
    data = _RepoPollData(branch=None, head_sha=None, prs={})
    try:
        client = GitHubAppClient(redis_client=r)
        try:
            token = await client.resolve_repo_token(repo)
        except Exception:
            logger.warning(
                "Poll: could not resolve a token for repo %s",
                repo.full_name,
                exc_info=True,
            )
            return data

        try:
            data.branch, data.head_sha = await client.get_default_branch_head(
                token, repo.full_name
            )
        except Exception:
            logger.warning(
                "Poll: failed to fetch default-branch head for %s",
                repo.full_name,
                exc_info=True,
            )

        for pr in prs:
            parsed = parse_pr_url(pr.pr_url or "")
            if not parsed:
                continue
            full_name, pr_number = parsed
            snapshot: PRSnapshot | None = None
            comments: list[str] = []
            try:
                snapshot = await client.get_pull_request_snapshot(
                    token, full_name, pr_number
                )
            except Exception:
                logger.warning(
                    "Poll: failed to snapshot PR %s#%s",
                    full_name,
                    pr_number,
                    exc_info=True,
                )
            try:
                comments = await client.list_pr_command_comments(
                    token, full_name, pr_number, pr.last_polled_comment_at
                )
            except Exception:
                logger.warning(
                    "Poll: failed to fetch comments for PR %s#%s",
                    full_name,
                    pr_number,
                    exc_info=True,
                )
            data.prs[pr.id] = _PRPollResult(
                snapshot=snapshot, command_comments=comments
            )
    finally:
        await r.aclose()
    return data


def _apply_push(
    session: Session, repo: Repository, data: _RepoPollData, now: datetime
) -> bool:
    """Enqueue a polled analysis when the default-branch head advanced.

    A NULL cursor (first poll) is treated as a baseline: it records the current
    head without firing, so onboarding a repo doesn't trigger a spurious run.
    """
    if not data.head_sha or not data.branch:
        return False
    enqueued = False
    if repo.last_polled_head_sha is None:
        pass  # baseline
    elif data.head_sha != repo.last_polled_head_sha:
        eh.enqueue_workflow_analysis(
            repo, data.branch, data.head_sha, AnalysisTrigger.polled_push
        )
        # External repos receive no webhooks, so this is their only path to an
        # IaC/Docker scan. Without these two calls a polled repo's Terraform
        # and Docker findings would never refresh after onboarding — the
        # webhook handler has always done both, the poller never did.
        # changed_paths is None because a poll observes only the new head, not
        # which files moved: every enabled target is rescanned.
        eh.enqueue_terraform_scans(
            session,
            repo,
            data.branch,
            data.head_sha,
            AnalysisTrigger.polled_push,
            changed_paths=None,
        )
        eh.enqueue_docker_scans(
            session,
            repo,
            data.branch,
            data.head_sha,
            AnalysisTrigger.polled_push,
            changed_paths=None,
        )
        enqueued = True
    repo.last_polled_head_sha = data.head_sha
    repo.last_polled_at = now
    session.add(repo)
    session.commit()
    return enqueued


def _lifecycle_event(pr: PullRequest, snapshot: PRSnapshot) -> str | None:
    """Map an observed PR state to a lifecycle event, or ``None`` if unchanged."""
    if snapshot.merged and pr.pr_state != PullRequestState.merged:
        return "merge"
    if snapshot.state == PullRequestState.closed and pr.pr_state not in (
        PullRequestState.closed,
        PullRequestState.merged,
    ):
        return "close"
    if (
        snapshot.state == PullRequestState.open
        and pr.pr_state == PullRequestState.closed
    ):
        return "reopen"
    return None


def _apply_pr(
    session: Session,
    repo: Repository,
    pr: PullRequest,
    result: _PRPollResult,
    now: datetime,
) -> None:
    """Drive the shared handlers off one PR's polled snapshot + comments."""
    snapshot = result.snapshot

    if snapshot is not None:
        # 1. Lifecycle (merge/close/reopen). A terminal transition ends this PR.
        event = _lifecycle_event(pr, snapshot)
        if event is not None:
            eh.handle_pull_request_lifecycle(session, pr, event)
            if event in ("merge", "close"):
                _apply_command_comments(session, repo, pr, result, now)
                return

        # 2. Draft toggle (open ⇆ draft).
        if snapshot.draft and pr.pr_state == PullRequestState.open:
            eh.handle_pull_request_draft_toggle(session, pr, "convert_to_draft")
        elif not snapshot.draft and pr.pr_state == PullRequestState.draft:
            eh.handle_pull_request_draft_toggle(session, pr, "mark_ready_for_review")

        # 3. Synchronize (new commits on the PR branch). NULL head is a baseline.
        if snapshot.head_sha and snapshot.head_sha != pr.head_sha:
            was_baseline = pr.head_sha is None
            pr.head_sha = snapshot.head_sha
            if was_baseline:
                session.add(pr)
                session.commit()
            else:
                eh.handle_pull_request_sync(
                    session, pr, mergeable_state=snapshot.mergeable_state
                )

        # 4. CI outcome.
        if snapshot.ci_status is not None and snapshot.ci_status != pr.ci_status:
            eh.handle_ci_status(session, pr, snapshot.ci_status)

        # 5. Review decision (``None`` = no decisive review, leave as-is).
        if (
            snapshot.review_decision is not None
            and snapshot.review_decision != pr.review_decision
        ):
            eh.handle_review_decision(session, pr, snapshot.review_decision)

    # 6. Slash commands on the PR.
    _apply_command_comments(session, repo, pr, result, now)


def _apply_command_comments(
    session: Session,
    repo: Repository,
    pr: PullRequest,
    result: _PRPollResult,
    now: datetime,
) -> None:
    for body in result.command_comments:
        command = eh.parse_greensecops_command(body)
        if command is not None:
            eh.handle_issue_command(session, repo, command)
    # Advance the cursor even when there were no commands, so the next poll's
    # ``since`` window doesn't re-scan the same comments.
    pr.last_polled_comment_at = now
    session.add(pr)
    session.commit()


def _poll_repository_impl(repo_id: str) -> dict[str, int | str]:
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        repo = session.get(Repository, uuid.UUID(repo_id))
        if not repo or not repo.enabled:
            return {"status": "skipped"}

        open_prs = list(
            session.exec(
                select(PullRequest)
                .where(PullRequest.repo_id == repo.id)
                .where(
                    col(PullRequest.pr_state).in_(
                        [PullRequestState.open, PullRequestState.draft]
                    )
                )
                .where(col(PullRequest.pr_url).is_not(None))
            ).all()
        )

        data = asyncio.run(_fetch_repo_poll_data(repo, open_prs))

        analyses = 1 if _apply_push(session, repo, data, now) else 0
        for pr in open_prs:
            result = data.prs.get(pr.id)
            if result is None:
                continue
            _apply_pr(session, repo, pr, result, now)

    return {"status": "ok", "prs": len(open_prs), "analyses_enqueued": analyses}


@celery_app.task(name="polling.poll_repository", bind=True)
def poll_repository(self: object, repo_id: str) -> dict[str, int | str]:  # noqa: ARG001
    return _poll_repository_impl(repo_id)


def _poll_repositories_impl(external_only: bool = True) -> dict[str, int | str]:
    with Session(engine) as session:
        query = select(Repository).where(Repository.enabled == True)  # noqa: E712
        if external_only:
            query = query.where(Repository.is_external == True)  # noqa: E712
        repos = list(session.exec(query).all())

    for i, repo in enumerate(repos):
        poll_repository.apply_async(
            kwargs={"repo_id": str(repo.id)},
            countdown=i * POLL_STAGGER_SECONDS,
        )
    logger.info(
        "Enqueued poll for %d repo(s) (external_only=%s)", len(repos), external_only
    )
    return {"status": "queued", "repos": len(repos)}


@celery_app.task(name="polling.poll_repositories", bind=True)
def poll_repositories(
    self: object,  # noqa: ARG001
    external_only: bool = True,
) -> dict[str, int | str]:
    return _poll_repositories_impl(external_only=external_only)
