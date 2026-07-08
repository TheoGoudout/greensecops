import logging
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Request
from sqlmodel import Session

from app import crud
from app.api.deps import SessionDep
from app.core.config import settings
from app.models import (
    AnalysisTrigger,
    Fix,
    Organization,
    PullRequest,
    PullRequestState,
    Repository,
)
from app.services.events import publisher as events_pub
from app.services.events import schemas as ev
from app.services.github.webhook_verifier import verify_webhook_signature

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


async def _is_duplicate_delivery(delivery_id: str | None) -> bool:
    """Redis-backed webhook delivery dedup (GitHub redelivers on retries).

    Fails open: when Redis is unavailable, processing a duplicate is safer
    than dropping a genuine event.
    """
    if not delivery_id:
        return False
    import redis.asyncio as aioredis

    try:
        r = aioredis.from_url(settings.REDIS_URL)
        try:
            fresh = await r.set(
                f"greensecops:webhook_delivery:{delivery_id}",
                "1",
                nx=True,
                ex=24 * 3600,
            )
        finally:
            await r.aclose()
        return not fresh
    except Exception:
        logger.warning("Webhook delivery dedup unavailable", exc_info=True)
        return False


@router.post("/github")
async def github_webhook(
    request: Request,
    session: SessionDep,
    x_hub_signature_256: Annotated[str | None, Header()] = None,
    x_github_event: Annotated[str | None, Header()] = None,
    x_github_delivery: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    payload_bytes = await request.body()

    # Fail closed: a webhook secret must be configured outside local dev, and the
    # signature must verify. Never process an unsigned/unverified webhook, which
    # could otherwise forge installations, disable repos or enqueue analyses.
    if not settings.GITHUB_WEBHOOK_SECRET:
        if settings.ENVIRONMENT == "local":
            logger.warning(
                "GITHUB_WEBHOOK_SECRET is not set — skipping signature verification "
                "(allowed only in local environment)"
            )
        else:
            raise HTTPException(status_code=503, detail="Webhook secret not configured")
    elif not verify_webhook_signature(
        payload_bytes, x_hub_signature_256, settings.GITHUB_WEBHOOK_SECRET
    ):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event = x_github_event or "unknown"
    logger.info("Received GitHub webhook event: %s", event)

    if await _is_duplicate_delivery(x_github_delivery):
        logger.info("Skipping duplicate webhook delivery %s", x_github_delivery)
        return {"status": "duplicate", "event": event}

    # Handlers enqueue work synchronously so an enqueue failure surfaces as a
    # 500 in GitHub's webhook log (a lost 200 would silently drop the event).
    if event == "push":
        _handle_push_event(session, payload)
    elif event == "workflow_run":
        _handle_workflow_run_event(session, payload)
    elif event == "issue_comment":
        _handle_issue_comment_event(session, payload)
    elif event == "installation":
        _handle_installation_event(session, payload)
    elif event == "installation_repositories":
        _handle_installation_repositories_event(session, payload)
    elif event == "pull_request":
        _handle_pull_request_event(session, payload)
    elif event == "repository":
        _handle_repository_event(session, payload)

    return {"status": "accepted", "event": event}


def _handle_push_event(
    session: Session,
    payload: dict[str, Any],
) -> None:
    """Trigger analysis when a push touches .github/workflows/ files or creates a new branch."""
    before: str = payload.get("before", "")
    is_new_branch = before == "0" * 40
    commits: list[dict[str, Any]] = payload.get("commits", [])
    touches_workflows = any(
        any(
            f.startswith(".github/workflows/")
            for f in (c.get("added", []) + c.get("modified", []) + c.get("removed", []))
        )
        for c in commits
    )
    if not touches_workflows and not is_new_branch:
        return

    repo_payload = payload.get("repository", {})
    github_repo_id = repo_payload.get("id")
    if not github_repo_id:
        return

    from sqlmodel import select

    repo = session.exec(
        select(Repository).where(Repository.github_repo_id == github_repo_id)
    ).first()
    if not repo or not repo.enabled:
        return

    branch = payload.get("ref", "").removeprefix("refs/heads/")
    commit_sha = payload.get("after", "")
    _enqueue_static_analysis(
        repo_id=str(repo.id),
        branch=branch,
        commit_sha=commit_sha,
        trigger=AnalysisTrigger.webhook_push,
        org_id=str(repo.org_id),
    )


def _handle_workflow_run_event(
    session: Session,
    payload: dict[str, Any],
) -> None:
    if payload.get("action") != "completed":
        return

    repo_payload = payload.get("repository", {})
    github_repo_id = repo_payload.get("id")
    if not github_repo_id:
        return

    from sqlmodel import select

    repo = session.exec(
        select(Repository).where(Repository.github_repo_id == github_repo_id)
    ).first()
    if not repo or not repo.enabled:
        return

    workflow_run = payload.get("workflow_run", {})
    branch = workflow_run.get("head_branch", "")
    commit_sha = workflow_run.get("head_sha", "")
    _enqueue_static_analysis(
        repo_id=str(repo.id),
        branch=branch,
        org_id=str(repo.org_id),
        commit_sha=commit_sha,
        trigger=AnalysisTrigger.webhook_workflow_run,
    )


def _handle_issue_comment_event(
    session: Session,
    payload: dict[str, Any],
) -> None:
    """Handle /greensecops commands in issue and PR comments."""
    if payload.get("action") != "created":
        return
    body: str = payload.get("comment", {}).get("body", "")
    stripped = body.strip()
    if not stripped.startswith("/greensecops"):
        return
    logger.info("Received GreenSecOps command comment: %s", body[:100])

    command = stripped.removeprefix("/greensecops").strip().split()
    if not command or command[0] != "reanalyze":
        # Other commands (fix, ignore, ...) are not implemented yet.
        return

    github_repo_id = payload.get("repository", {}).get("id")
    if not github_repo_id:
        return

    from sqlmodel import select

    repo = session.exec(
        select(Repository).where(Repository.github_repo_id == github_repo_id)
    ).first()
    if not repo or not repo.enabled:
        return

    _enqueue_static_analysis(
        repo_id=str(repo.id),
        branch=repo.default_branch,
        commit_sha="",
        trigger=AnalysisTrigger.manual,
        org_id=str(repo.org_id),
        force=True,
    )


def _handle_repository_event(
    session: Session,
    payload: dict[str, Any],
) -> None:
    """Keep repository metadata in sync (rename, transfer, default branch, deletion).

    Without this, ``full_name``/``default_branch`` go stale and later fix
    deliveries fail when resolving the repo or its base branch.
    """
    action = payload.get("action")
    repo_payload = payload.get("repository", {})
    github_repo_id = repo_payload.get("id")
    if not github_repo_id:
        return

    from sqlmodel import select

    repo = session.exec(
        select(Repository).where(Repository.github_repo_id == github_repo_id)
    ).first()
    if not repo:
        return

    if action in ("deleted", "archived"):
        repo.enabled = False
        session.add(repo)
        session.commit()
        logger.info("Disabled repo %s after %s event", repo.full_name, action)
        events_pub.publish_event(
            ev.repository_disabled(str(repo.org_id), [str(repo.id)])
        )
        return

    if action == "unarchived":
        repo.enabled = True
        session.add(repo)
        session.commit()
        logger.info("Re-enabled repo %s after unarchive", repo.full_name)
        return

    if action in ("renamed", "transferred", "edited"):
        changed = False
        new_full_name = repo_payload.get("full_name")
        if new_full_name and new_full_name != repo.full_name:
            logger.info("Repo renamed: %s -> %s", repo.full_name, new_full_name)
            repo.full_name = new_full_name
            changed = True
        new_default_branch = repo_payload.get("default_branch")
        if new_default_branch and new_default_branch != repo.default_branch:
            logger.info(
                "Repo %s default branch: %s -> %s",
                repo.full_name,
                repo.default_branch,
                new_default_branch,
            )
            repo.default_branch = new_default_branch
            changed = True
        if changed:
            session.add(repo)
            session.commit()


def _handle_installation_event(
    session: Session,
    payload: dict[str, Any],
) -> None:
    """Record GitHub App installation lifecycle events."""
    action = payload.get("action")
    installation = payload.get("installation", {})
    installation_id = installation.get("id")
    if not installation_id:
        return

    if action in ("deleted", "suspend"):
        from sqlmodel import select

        repos = session.exec(
            select(Repository).where(Repository.installation_id == installation_id)
        ).all()
        for repo in repos:
            repo.enabled = False
        session.commit()
        logger.info(
            "Disabled %d repos for %s installation %s",
            len(repos),
            action,
            installation_id,
        )
        if repos:
            org_id = str(repos[0].org_id)
            if action == "deleted":
                events_pub.publish_event(
                    ev.installation_deleted(org_id, installation_id, len(repos))
                )
            else:
                events_pub.publish_event(
                    ev.installation_suspended(org_id, installation_id, len(repos))
                )
            events_pub.publish_event(
                ev.repository_disabled(org_id, [str(r.id) for r in repos])
            )
        return

    if action in ("created", "unsuspend", "new_permissions_accepted"):
        org = _upsert_org_from_installation(session, installation)
        if org is None:
            return
        if action == "created":
            events_pub.publish_event(
                ev.installation_created(str(org.id), installation_id, org.name)
            )
        elif action == "unsuspend":
            events_pub.publish_event(
                ev.installation_unsuspended(str(org.id), installation_id, org.name)
            )
        else:
            events_pub.publish_event(
                ev.installation_updated(str(org.id), installation_id, org.name)
            )
        # Ownership is linked by the authenticated /installations/sync endpoint
        # (the webhook has no app-session user); here we only ensure repos load.
        _enqueue_installation_sync(installation_id, str(org.id))


def _handle_pull_request_event(
    session: Session,
    payload: dict[str, Any],
) -> None:
    action = payload.get("action")
    if action not in ("closed", "reopened"):
        return

    pr = payload.get("pull_request", {})
    pr_url = pr.get("html_url")
    if not pr_url:
        return

    if action == "closed":
        merged = pr.get("merged", False)
        new_state = PullRequestState.merged if merged else PullRequestState.closed
    else:
        merged = False
        new_state = PullRequestState.open

    from sqlmodel import select

    pr_record = session.exec(
        select(PullRequest).where(PullRequest.pr_url == pr_url)
    ).first()
    if not pr_record:
        return

    pr_record.pr_state = new_state
    session.add(pr_record)
    session.commit()
    logger.info("PR %s -> state=%s for PR record %s", pr_url, new_state, pr_record.id)

    # Notify for all fixes associated with this PR
    pr_fixes = list(session.exec(select(Fix).where(Fix.pr_id == pr_record.id)).all())
    fix = pr_fixes[0] if pr_fixes else None
    if fix:
        repo = session.get(Repository, pr_record.repo_id)
        if repo:
            if action == "closed":
                events_pub.publish_event(
                    ev.pr_closed(
                        str(repo.org_id), str(repo.id), str(fix.id), pr_url, merged
                    )
                )
            else:
                events_pub.publish_event(
                    ev.pr_opened(
                        str(repo.org_id),
                        str(repo.id),
                        [str(fix.id)],
                        pr_url,
                        pr_record.pr_branch,
                    )
                )


def _handle_installation_repositories_event(
    session: Session,
    payload: dict[str, Any],
) -> None:
    """Handle repos added/removed from an existing installation."""
    action = payload.get("action")
    installation = payload.get("installation", {})
    installation_id = installation.get("id")
    if not installation_id:
        return

    if action == "added":
        org = _upsert_org_from_installation(session, installation)
        if org is None:
            return
        # The payload lacks default_branch, so re-sync for accurate data.
        _enqueue_installation_sync(installation_id, str(org.id))
    elif action == "removed":
        removed: list[dict[str, Any]] = payload.get("repositories_removed", [])
        github_repo_ids = [r["id"] for r in removed if r.get("id")]
        count = crud.disable_repositories_by_github_ids(
            session=session, github_repo_ids=github_repo_ids
        )
        logger.info(
            "Disabled %d removed repos for installation %s", count, installation_id
        )
        org = _upsert_org_from_installation(session, installation)
        if org and count:
            events_pub.publish_event(
                ev.repository_disabled(
                    str(org.id), [str(gid) for gid in github_repo_ids]
                )
            )


def _upsert_org_from_installation(
    session: Session, installation: dict[str, Any]
) -> Organization | None:
    """Resolve/create the Organization for an installation payload."""
    installation_id = installation.get("id")
    account = installation.get("account") or {}
    account_id = account.get("id")
    account_login = account.get("login")
    if not account_id or not account_login:
        logger.warning(
            "Installation %s missing account info; skipping org upsert",
            installation_id,
        )
        return None
    return crud.upsert_organization(
        session=session,
        github_org_id=account_id,
        name=account_login,
        installation_id=installation_id,
    )


def _enqueue_static_analysis(
    repo_id: str,
    branch: str,
    commit_sha: str,
    trigger: AnalysisTrigger,
    org_id: str = "",
    force: bool = False,
) -> None:
    from app.services.events import publisher as events_pub
    from app.services.events import schemas as ev
    from app.workers.tasks.static_analysis import run_static_analysis

    run_static_analysis.delay(
        repo_id=repo_id,
        branch=branch,
        commit_sha=commit_sha,
        trigger=trigger.value,
        force=force,
    )
    if org_id:
        events_pub.publish_event(
            ev.analysis_queued(org_id, repo_id, branch, trigger.value)
        )


def _enqueue_installation_sync(installation_id: int, org_id: str) -> None:
    from app.workers.tasks.installation_sync import sync_installation_repositories

    sync_installation_repositories.delay(
        installation_id=installation_id,
        org_id=org_id,
    )
