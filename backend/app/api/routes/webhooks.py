import logging
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from sqlmodel import Session

from app.api.deps import SessionDep
from app.core.config import settings
from app.models import (
    AnalysisTrigger,
    Repository,
)
from app.services.github.app_client import GitHubAppClient
from app.services.github.webhook_verifier import verify_webhook_signature

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _get_github_app_client_sync() -> GitHubAppClient:
    """Placeholder — replaced by proper async dep in route."""
    raise NotImplementedError


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

    return {"status": "accepted", "event": event}


def _handle_push_event(
    session: Session,
    payload: dict[str, Any],
    background_tasks: BackgroundTasks,
) -> None:
    """Trigger analysis when a push touches .github/workflows/ files."""
    commits: list[dict[str, Any]] = payload.get("commits", [])
    touches_workflows = any(
        any(
            f.startswith(".github/workflows/")
            for f in (c.get("added", []) + c.get("modified", []) + c.get("removed", []))
        )
        for c in commits
    )
    if not touches_workflows:
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
    """Record new GitHub App installations."""
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
