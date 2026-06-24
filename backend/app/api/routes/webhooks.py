import logging
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from sqlmodel import Session

from app import crud
from app.api.deps import SessionDep
from app.core.config import settings
from app.models import (
    Analysis,
    AnalysisTrigger,
    Fix,
    Issue,
    Organization,
    Repository,
)
from app.services.events import publisher as events_pub
from app.services.events import schemas as ev
from app.services.github.webhook_verifier import verify_webhook_signature

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/github")
async def github_webhook(
    request: Request,
    session: SessionDep,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: Annotated[str | None, Header()] = None,
    x_github_event: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    payload_bytes = await request.body()

    # Verify signature when secret is configured
    if settings.GITHUB_WEBHOOK_SECRET:
        if not verify_webhook_signature(
            payload_bytes, x_hub_signature_256, settings.GITHUB_WEBHOOK_SECRET
        ):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event = x_github_event or "unknown"
    logger.info("Received GitHub webhook event: %s", event)

    if event == "push":
        _handle_push_event(session, payload, background_tasks)
    elif event == "workflow_run":
        _handle_workflow_run_event(session, payload, background_tasks)
    elif event == "issue_comment":
        _handle_issue_comment_event(session, payload, background_tasks)
    elif event == "installation":
        _handle_installation_event(session, payload)
    elif event == "installation_repositories":
        _handle_installation_repositories_event(session, payload)
    elif event == "pull_request":
        _handle_pull_request_event(session, payload)

    return {"status": "accepted", "event": event}


def _handle_push_event(
    session: Session,
    payload: dict[str, Any],
    background_tasks: BackgroundTasks,
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
    background_tasks.add_task(
        _enqueue_static_analysis,
        repo_id=str(repo.id),
        branch=branch,
        commit_sha=commit_sha,
        trigger=AnalysisTrigger.webhook_push,
    )


def _handle_workflow_run_event(
    session: Session,
    payload: dict[str, Any],
    background_tasks: BackgroundTasks,
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
    background_tasks.add_task(
        _enqueue_static_analysis,
        repo_id=str(repo.id),
        branch=branch,
        commit_sha=commit_sha,
        trigger=AnalysisTrigger.webhook_workflow_run,
    )


def _handle_issue_comment_event(
    session: Session,  # noqa: ARG001
    payload: dict[str, Any],
    background_tasks: BackgroundTasks,  # noqa: ARG001
) -> None:
    """Handle /greensecops commands in PR comments."""
    if payload.get("action") != "created":
        return
    body: str = payload.get("comment", {}).get("body", "")
    if not body.strip().startswith("/greensecops"):
        return
    # Future: parse commands like /greensecops fix, /greensecops ignore
    logger.info("Received GreenSecOps command comment: %s", body[:100])


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
            "Disabled %d repos for uninstalled installation %s",
            len(repos),
            installation_id,
        )
        if repos:
            org_id = str(repos[0].org_id)
            events_pub.publish_event(
                ev.installation_deleted(org_id, installation_id, len(repos))
            )
            events_pub.publish_event(
                ev.repository_disabled(org_id, [str(r.id) for r in repos])
            )
        return

    if action in ("created", "unsuspend", "new_permissions_accepted"):
        org = _upsert_org_from_installation(session, installation)
        if org is None:
            return
        events_pub.publish_event(
            ev.installation_created(str(org.id), installation_id, org.name)
        )
        # Ownership is linked by the authenticated /installations/sync endpoint
        # (the webhook has no app-session user); here we only ensure repos load.
        _enqueue_installation_sync(installation_id, str(org.id))


def _handle_pull_request_event(
    session: Session,
    payload: dict[str, Any],
) -> None:
    if payload.get("action") != "closed":
        return

    pr = payload.get("pull_request", {})
    pr_url = pr.get("html_url")
    if not pr_url:
        return

    merged = pr.get("merged", False)
    new_state = "merged" if merged else "closed"

    from sqlmodel import select

    fix = session.exec(select(Fix).where(Fix.pr_url == pr_url)).first()
    if not fix:
        return

    fix.pr_state = new_state
    session.add(fix)
    session.commit()
    logger.info("PR %s -> state=%s for fix %s", pr_url, new_state, fix.id)

    issue = session.get(Issue, fix.issue_id)
    analysis = session.get(Analysis, issue.analysis_id) if issue else None
    repo = session.get(Repository, analysis.repo_id) if analysis else None
    if repo:
        events_pub.publish_event(
            ev.pr_closed(str(repo.org_id), str(repo.id), str(fix.id), pr_url, merged)
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
) -> None:
    from app.workers.tasks.static_analysis import run_static_analysis

    run_static_analysis.delay(
        repo_id=repo_id,
        branch=branch,
        commit_sha=commit_sha,
        trigger=trigger.value,
    )


def _enqueue_installation_sync(installation_id: int, org_id: str) -> None:
    from app.workers.tasks.installation_sync import sync_installation_repositories

    sync_installation_repositories.delay(
        installation_id=installation_id,
        org_id=org_id,
    )
