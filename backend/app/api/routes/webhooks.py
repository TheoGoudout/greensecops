import logging
from typing import Annotated, Any

from fastapi import Header, HTTPException, Request
from sqlmodel import Session, col, select

from app import crud
from app.api.deps import SessionDep
from app.api.router import Role, RoleRouter
from app.core.config import settings
from app.core.rate_limit import LIMIT_WEBHOOK
from app.models import (
    FindingResolutionReason,
    Fix,
    Issue,
    Organization,
    PullRequest,
    PullRequestState,
    Repository,
    ScanTrigger,
    WorkflowFile,
)
from app.services import state_machines as sm
from app.services.events import publisher as events_pub
from app.services.events import schemas as ev
from app.services.github import event_handlers as eh
from app.services.github.webhook_verifier import verify_webhook_signature

logger = logging.getLogger(__name__)

router = RoleRouter(prefix="/webhooks", tags=["webhooks"])


async def _is_duplicate_delivery(delivery_id: str | None) -> bool:
    """Redis-backed webhook delivery dedup (GitHub redelivers on retries).

    Fails open: when Redis is unavailable, processing a duplicate is safer
    than dropping a genuine event.
    """
    if not delivery_id:
        return False
    import redis.asyncio as aioredis

    try:
        r = aioredis.from_url(settings.REDIS_URL)  # type: ignore[no-untyped-call]
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


@router.post("/github", role=Role.service, limit=LIMIT_WEBHOOK)
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
    # Each handler only parses the payload and resolves the target row, then
    # delegates the actual work to the source-agnostic ``event_handlers`` shared
    # with the external-repo poller.
    if event == "push":
        _handle_push_event(session, payload)
    elif event == "delete":
        _handle_delete_event(session, payload)
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
    elif event == "check_suite":
        _handle_check_suite_event(session, payload)
    elif event == "pull_request_review":
        _handle_pull_request_review_event(session, payload)
    elif event == "repository":
        _handle_repository_event(session, payload)

    return {"status": "accepted", "event": event}


def _resolve_repo_by_github_id(
    session: Session, payload: dict[str, Any]
) -> Repository | None:
    """Resolve an enabled ``Repository`` from a payload's ``repository.id``."""
    github_repo_id = payload.get("repository", {}).get("id")
    if not github_repo_id:
        return None
    repo = session.exec(
        select(Repository).where(Repository.github_repo_id == github_repo_id)
    ).first()
    if not repo or not repo.enabled:
        return None
    return repo


def _handle_push_event(
    session: Session,
    payload: dict[str, Any],
) -> None:
    """Trigger analysis when a push touches .github/workflows/ files or creates a new branch."""
    # Branch deletion also emits a push (after = 0-sha, empty commits); the
    # dedicated ``delete`` handler owns cleanup.
    if payload.get("deleted"):
        return

    github_repo_id = payload.get("repository", {}).get("id")
    if not github_repo_id:
        return
    # Resolved without the ``enabled`` gate: a push to a greensecops/* fix
    # branch must flag the PR even while analysis is disabled.
    repo = session.exec(
        select(Repository).where(Repository.github_repo_id == github_repo_id)
    ).first()
    if not repo:
        return

    branch = payload.get("ref", "").removeprefix("refs/heads/")
    if branch.startswith("greensecops/"):
        # Never analyse our own fix branches — but a push to one by anyone
        # other than the bot means the user edited the fix PR, which must
        # block auto-redelivery (it would overwrite their commits).
        _flag_externally_modified_fix_branch(session, repo, branch, payload)
        return
    if not repo.enabled:
        return

    # A push to the base branch can silently conflict our open fix PRs —
    # GitHub sends no webhook for that. Refresh their mergeable_state
    # (attribute only; never auto-rebase).
    if branch == repo.default_branch:
        _enqueue_pr_mergeable_refresh(session, repo)

    before: str = payload.get("before", "")
    is_new_branch = before == "0" * 40
    # A force-push (rebase, reset) can change the branch's effective workflow
    # content while the payload's commits never mention a workflow path (the
    # dropped commits aren't listed). Re-analyse unconditionally: branch-scoped
    # content dedup makes an unchanged tree a cheap no-op.
    forced = bool(payload.get("forced"))
    commits: list[dict[str, Any]] = payload.get("commits", [])
    changed_paths = {
        f
        for c in commits
        for f in (c.get("added", []) + c.get("modified", []) + c.get("removed", []))
    }
    touches_workflows = any(f.startswith(".github/workflows/") for f in changed_paths)

    commit_sha = payload.get("after", "")
    if touches_workflows or is_new_branch or forced:
        eh.enqueue_workflow_analysis(repo, branch, commit_sha, ScanTrigger.webhook_push)
    # Independent of the workflow-analysis gate above: a push that only
    # touches Terraform files (no .github/workflows/ change) must still
    # trigger a scan.
    eh.enqueue_terraform_scans(
        session,
        repo,
        branch,
        commit_sha,
        ScanTrigger.webhook_push,
        changed_paths=None if (is_new_branch or forced) else changed_paths,
    )
    eh.enqueue_docker_scans(
        session,
        repo,
        branch,
        commit_sha,
        ScanTrigger.webhook_push,
        changed_paths=None if (is_new_branch or forced) else changed_paths,
    )


def _flag_externally_modified_fix_branch(
    session: Session,
    repo: Repository,
    branch: str,
    payload: dict[str, Any],
) -> None:
    """Mark a fix PR as user-edited when a non-bot pushes to its branch.

    ``externally_modified`` blocks auto-redelivery (fix_generation) so the
    user's commits aren't overwritten; a successful forced delivery clears it.
    The delivery service's own user-commit guard remains the backstop.
    """
    from datetime import datetime, timezone

    from app.services.github.fix_delivery import is_bot_login

    sender_login = payload.get("sender", {}).get("login")
    if is_bot_login(sender_login, settings.GITHUB_BOT_HANDLE):
        return

    pr_record = session.exec(
        select(PullRequest)
        .where(PullRequest.repo_id == repo.id)
        .where(PullRequest.pr_branch == branch)
    ).first()
    if pr_record is None or pr_record.externally_modified:
        return
    pr_record.externally_modified = True
    pr_record.updated_at = datetime.now(timezone.utc)
    sm.try_advance(pr_record, sm.PullRequestMachine, "external_update")
    session.add(pr_record)
    session.commit()
    logger.info(
        "Fix branch %s of %s modified by %s: auto-redelivery blocked",
        branch,
        repo.full_name,
        sender_login,
    )
    if pr_record.pr_url:
        fix = session.exec(select(Fix).where(Fix.pr_id == pr_record.id)).first()
        if fix:
            events_pub.publish_event(
                ev.pr_updated(
                    str(repo.org_id),
                    str(repo.id),
                    [str(fix.id)],
                    pr_record.pr_url,
                    pr_record.pr_branch,
                )
            )


def _handle_delete_event(
    session: Session,
    payload: dict[str, Any],
) -> None:
    """Reconcile state when a branch is deleted.

    A ``greensecops/*`` fix branch deleted by hand closes its PR record and
    withdraws its fixes (GitHub closes the PR too, but that webhook may never
    come if no PR existed). Any other branch resolves that branch's open
    issues with reason ``branch_deleted`` — their workflow files no longer
    exist anywhere. WorkflowFile rows are kept (deleting would cascade the
    audit history, see docs/state-machines.md §8).
    """
    if payload.get("ref_type") != "branch":
        return
    branch: str = payload.get("ref", "")
    github_repo_id = payload.get("repository", {}).get("id")
    if not branch or not github_repo_id:
        return

    # No ``enabled`` gate: cleanup applies to disabled repos too.
    repo = session.exec(
        select(Repository).where(Repository.github_repo_id == github_repo_id)
    ).first()
    if not repo:
        return
    # GitHub forbids deleting the default branch; guard anyway.
    if branch == repo.default_branch:
        return

    if branch.startswith("greensecops/"):
        pr_record = session.exec(
            select(PullRequest)
            .where(PullRequest.repo_id == repo.id)
            .where(PullRequest.pr_branch == branch)
        ).first()
        if pr_record and pr_record.pr_state not in (
            PullRequestState.closed,
            PullRequestState.merged,
        ):
            logger.info(
                "Fix branch %s deleted: closing PR record %s", branch, pr_record.id
            )
            eh.handle_pull_request_lifecycle(session, pr_record, "close")
        return

    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    wf_rows = session.exec(
        select(WorkflowFile)
        .where(WorkflowFile.repo_id == repo.id)
        .where(WorkflowFile.branch == branch)
    ).all()
    resolved = 0
    superseded = 0
    for wf in wf_rows:
        open_issues = session.exec(
            select(Issue)
            .where(Issue.workflow_file_id == wf.id)
            .where(col(Issue.resolved_at).is_(None))
        ).all()
        for issue in open_issues:
            issue.resolved_at = now
            issue.resolution_reason = FindingResolutionReason.branch_deleted
            session.add(issue)
            resolved += 1
        # Fixes are default-branch-only, but a legacy feature-branch fix (from
        # before the branch dimension) is withdrawn defensively.
        if wf.fix is not None and sm.try_advance(
            wf.fix, sm.FixMachine, "supersede_deleted_file"
        ):
            session.add(wf.fix)
            superseded += 1
    if resolved or superseded:
        session.commit()
        logger.info(
            "Branch %s of %s deleted: resolved %d issue(s), superseded %d fix(es)",
            branch,
            repo.full_name,
            resolved,
            superseded,
        )


def _handle_workflow_run_event(
    session: Session,
    payload: dict[str, Any],
) -> None:
    if payload.get("action") != "completed":
        return

    repo = _resolve_repo_by_github_id(session, payload)
    if not repo:
        return

    workflow_run = payload.get("workflow_run", {})
    branch = workflow_run.get("head_branch", "")
    commit_sha = workflow_run.get("head_sha", "")
    eh.enqueue_workflow_analysis(
        repo, branch, commit_sha, ScanTrigger.webhook_workflow_run
    )


def _handle_issue_comment_event(
    session: Session,
    payload: dict[str, Any],
) -> None:
    """Handle /greensecops commands in issue and PR comments."""
    if payload.get("action") != "created":
        return
    body: str = payload.get("comment", {}).get("body", "")
    if not body.strip().startswith("/greensecops"):
        return
    logger.info("Received GreenSecOps command comment: %s", body[:100])

    command = eh.parse_greensecops_command(body)
    if not command:
        return

    repo = _resolve_repo_by_github_id(session, payload)
    if not repo:
        return

    eh.handle_issue_command(session, repo, command)


def _handle_repository_event(
    session: Session,
    payload: dict[str, Any],
) -> None:
    """Keep repository metadata in sync (rename, transfer, default branch, deletion).

    Without this, ``full_name``/``default_branch`` go stale and later fix
    deliveries fail when resolving the repo or its base branch.

    Webhook-only: repository lifecycle has no external-repo polling analogue.
    """
    action = payload.get("action")
    repo_payload = payload.get("repository", {})
    github_repo_id = repo_payload.get("id")
    if not github_repo_id:
        return

    repo = session.exec(
        select(Repository).where(Repository.github_repo_id == github_repo_id)
    ).first()
    if not repo:
        return

    if action in ("deleted", "archived"):
        # ``archived`` is a reversible GitHub state (→ archived); ``deleted``
        # removes the repo (→ inaccessible). Both keep ``enabled=False`` (user
        # opt-in is a separate axis) and drop ``is_accessible`` via the machine.
        repo.enabled = False
        event_name = "archive" if action == "archived" else "lose_access"
        moved = sm.try_advance(repo, sm.RepositoryMachine, event_name)
        sm.sync_access_flag(repo)
        session.add(repo)
        session.commit()
        logger.info(
            "Repo %s -> status=%s after %s", repo.full_name, repo.status, action
        )
        signal = sm.output_for(sm.RepositoryMachine, event_name)
        if moved and signal is not None:
            events_pub.publish_event(
                ev.repository_status_changed(str(repo.org_id), [str(repo.id)], signal)
            )
        return

    if action == "unarchived":
        repo.enabled = True
        moved = sm.try_advance(repo, sm.RepositoryMachine, "unarchive")
        sm.sync_access_flag(repo)
        session.add(repo)
        session.commit()
        logger.info("Re-enabled repo %s after unarchive", repo.full_name)
        signal = sm.output_for(sm.RepositoryMachine, "unarchive")
        if moved and signal is not None:
            events_pub.publish_event(
                ev.repository_status_changed(str(repo.org_id), [str(repo.id)], signal)
            )
        return

    if action in ("renamed", "transferred", "edited"):
        changed = False
        new_full_name = repo_payload.get("full_name")
        if new_full_name and new_full_name != repo.full_name:
            logger.info("Repo renamed: %s -> %s", repo.full_name, new_full_name)
            repo.full_name = new_full_name
            changed = True
        new_default_branch = repo_payload.get("default_branch")
        default_branch_changed = bool(
            new_default_branch and new_default_branch != repo.default_branch
        )
        if default_branch_changed:
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
        if default_branch_changed and repo.enabled:
            # Everything default-branch-scoped (grades, fixes, the default
            # issue listing) now keys off the new branch; analyse it so its
            # WorkflowFile rows exist. Old-branch fixes/PRs retire naturally
            # via the default-branch gates.
            eh.enqueue_workflow_analysis(
                repo, repo.default_branch, "", ScanTrigger.manual
            )


def _handle_installation_event(
    session: Session,
    payload: dict[str, Any],
) -> None:
    """Record GitHub App installation lifecycle events.

    Webhook-only: installations have no external-repo polling analogue.
    """
    action = payload.get("action")
    installation = payload.get("installation", {})
    installation_id = installation.get("id")
    if not installation_id:
        return

    if action in ("deleted", "suspend"):
        repos = crud.mark_repositories_inaccessible_by_installation_id(
            session=session,
            installation_id=installation_id,
            event="suspend" if action == "suspend" else "lose_access",
        )
        logger.info(
            "Marked %d repos inaccessible for %s installation %s",
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
        if action == "unsuspend":
            crud.restore_repositories_accessibility_by_installation_id(
                session=session, installation_id=installation_id
            )
            events_pub.publish_event(
                ev.installation_unsuspended(str(org.id), installation_id, org.name)
            )
        elif action == "created":
            events_pub.publish_event(
                ev.installation_created(str(org.id), installation_id, org.name)
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
    if action not in (
        "opened",
        "closed",
        "reopened",
        "synchronize",
        "edited",
        "converted_to_draft",
        "ready_for_review",
    ):
        return

    pr = payload.get("pull_request", {})
    pr_url = pr.get("html_url")
    if not pr_url:
        return

    if action == "opened":
        _handle_pull_request_opened(session, payload, pr, pr_url)
        return

    pr_record = session.exec(
        select(PullRequest).where(PullRequest.pr_url == pr_url)
    ).first()
    if not pr_record:
        return

    # Draft toggles: converted_to_draft (open -> draft) / ready_for_review
    # (draft -> open).
    if action in ("converted_to_draft", "ready_for_review"):
        draft_event = (
            "convert_to_draft"
            if action == "converted_to_draft"
            else "mark_ready_for_review"
        )
        eh.handle_pull_request_draft_toggle(session, pr_record, draft_event)
        return

    # New commits pushed to the PR branch (synchronize) or a title/base edit
    # (edited): record the update without changing lifecycle state.
    if action in ("synchronize", "edited"):
        eh.handle_pull_request_sync(
            session, pr_record, mergeable_state=pr.get("mergeable_state")
        )
        return

    if action == "closed":
        pr_event = "merge" if pr.get("merged", False) else "close"
    else:
        pr_event = "reopen"
    eh.handle_pull_request_lifecycle(session, pr_record, pr_event)


def _handle_pull_request_opened(
    session: Session,
    payload: dict[str, Any],
    pr: dict[str, Any],
    pr_url: str,
) -> None:
    """Link a manually opened PR from a ``greensecops/*`` fix branch.

    Delivery normally creates the PR (and its record) itself; this covers a
    user opening a PR by hand from a fix branch the bot pushed — without it
    the PR's lifecycle (close/merge/reopen) would never be tracked.
    """
    head_ref: str = pr.get("head", {}).get("ref", "")
    if not head_ref.startswith("greensecops/"):
        return
    github_repo_id = payload.get("repository", {}).get("id")
    if not github_repo_id:
        return

    repo = session.exec(
        select(Repository).where(Repository.github_repo_id == github_repo_id)
    ).first()
    if not repo:
        return

    pr_record = session.exec(
        select(PullRequest)
        .where(PullRequest.repo_id == repo.id)
        .where(PullRequest.pr_branch == head_ref)
    ).first()
    if pr_record is None:
        pr_record = PullRequest(
            repo_id=repo.id,
            pr_branch=head_ref,
            pr_url=pr_url,
            pr_state=PullRequestState.open,
        )
        session.add(pr_record)
        session.commit()
        logger.info("Linked externally opened fix PR %s (%s)", pr_url, head_ref)
        return
    # An existing record: fill a missing URL and reopen a closed record —
    # opening a PR from a branch whose previous PR closed is a fresh start.
    if not pr_record.pr_url:
        pr_record.pr_url = pr_url
    sm.try_advance(pr_record, sm.PullRequestMachine, "reopen")
    session.add(pr_record)
    session.commit()


def _handle_check_suite_event(
    session: Session,
    payload: dict[str, Any],
) -> None:
    """Record CI outcome (an attribute, not a state) from a check_suite event."""
    suite = payload.get("check_suite", {})
    head_branch = suite.get("head_branch")
    github_repo_id = payload.get("repository", {}).get("id")
    if not head_branch or not github_repo_id:
        return
    repo = session.exec(
        select(Repository).where(Repository.github_repo_id == github_repo_id)
    ).first()
    if not repo:
        return
    pr_record = session.exec(
        select(PullRequest)
        .where(PullRequest.repo_id == repo.id)
        .where(PullRequest.pr_branch == head_branch)
    ).first()
    if not pr_record:
        return
    ci_status = eh.ci_status_from_conclusion(
        suite.get("status", ""), suite.get("conclusion")
    )
    eh.handle_ci_status(session, pr_record, ci_status)


def _handle_pull_request_review_event(
    session: Session,
    payload: dict[str, Any],
) -> None:
    """Record the latest review decision (an attribute) from a review event."""
    if payload.get("action") not in ("submitted", "dismissed"):
        return
    decision = eh.review_state_to_decision(payload.get("review", {}).get("state") or "")
    if decision is None:
        # A plain comment review carries no decision — leave the current value.
        return
    pr_url = payload.get("pull_request", {}).get("html_url")
    if not pr_url:
        return
    pr_record = session.exec(
        select(PullRequest).where(PullRequest.pr_url == pr_url)
    ).first()
    if not pr_record:
        return
    eh.handle_review_decision(session, pr_record, decision)


def _handle_installation_repositories_event(
    session: Session,
    payload: dict[str, Any],
) -> None:
    """Handle repos added/removed from an existing installation.

    Webhook-only: installation membership has no external-repo polling analogue.
    """
    action = payload.get("action")
    installation = payload.get("installation", {})
    installation_id = installation.get("id")
    if not installation_id:
        return

    if action == "added":
        org = _upsert_org_from_installation(session, installation)
        if org is None:
            return
        added: list[dict[str, Any]] = payload.get("repositories_added", [])
        github_repo_ids = [r["id"] for r in added if r.get("id")]
        if github_repo_ids:
            repos = list(
                session.exec(
                    select(Repository).where(
                        col(Repository.github_repo_id).in_(github_repo_ids)
                    )
                ).all()
            )
            for repo in repos:
                # Re-added to the installation: regain access (machine syncs
                # is_accessible). ``enabled`` (user opt-in) stays as-is.
                sm.try_advance(repo, sm.RepositoryMachine, "regain_access")
                sm.sync_access_flag(repo)
                session.add(repo)
            session.commit()
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


_PR_MERGEABLE_DEDUP_TTL = 300  # seconds


def _enqueue_pr_mergeable_refresh(session: Session, repo: Repository) -> None:
    """Queue a mergeable_state refresh of the repo's open fix PRs.

    Redis-deduped (fail-open) so a burst of pushes to the default branch
    yields one refresh per TTL window. Skipped when the repo has no open
    fix PR — the common case for every default-branch push.
    """
    has_open_pr = (
        session.exec(
            select(PullRequest.id)
            .where(PullRequest.repo_id == repo.id)
            .where(
                col(PullRequest.pr_state).in_(
                    [PullRequestState.open, PullRequestState.draft]
                )
            )
            .where(col(PullRequest.pr_url).is_not(None))
            .limit(1)
        ).first()
        is not None
    )
    if not has_open_pr:
        return

    import redis as redis_sync

    try:
        r = redis_sync.Redis.from_url(settings.REDIS_URL)
        try:
            key = f"greensecops:queued:pr_mergeable:{repo.id}"
            if not r.set(key, "1", nx=True, ex=_PR_MERGEABLE_DEDUP_TTL):
                return
        finally:
            r.close()
    except Exception:
        logger.warning(
            "Redis unavailable for PR mergeable refresh dedup; enqueuing anyway",
            exc_info=True,
        )

    from app.workers.tasks.maintenance import refresh_pr_mergeable_state

    refresh_pr_mergeable_state.delay(repo_id=str(repo.id))


_INSTALLATION_SYNC_DEDUP_TTL = 90  # seconds


def _enqueue_installation_sync(installation_id: int, org_id: str) -> None:
    """Enqueue an installation sync, skipping if one is already queued.

    GitHub fires both `installation` and `installation_repositories` events
    simultaneously on app install; this dedup prevents the resulting duplicate
    sync tasks from each enqueueing analyses for the same repos.
    Fails open: when Redis is unavailable the task is enqueued anyway.
    """
    import redis as redis_sync

    try:
        r = redis_sync.Redis.from_url(settings.REDIS_URL)
        try:
            key = f"greensecops:queued:installation_sync:{installation_id}"
            if not r.set(key, "1", nx=True, ex=_INSTALLATION_SYNC_DEDUP_TTL):
                logger.info(
                    "Installation sync already queued for installation %s, skipping",
                    installation_id,
                )
                return
        finally:
            r.close()
    except Exception:
        logger.warning(
            "Redis unavailable for installation sync dedup; enqueuing anyway",
            exc_info=True,
        )

    from app.workers.tasks.installation_sync import sync_installation_repositories

    sync_installation_repositories.delay(
        installation_id=installation_id,
        org_id=org_id,
    )
