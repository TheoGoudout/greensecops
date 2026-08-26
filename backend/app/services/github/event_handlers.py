"""Source-agnostic GitHub event handlers.

The business logic for a GitHub event — advancing a state machine, landing or
superseding fixes, resolving issues, publishing SSE, enqueuing analysis — is the
same regardless of how we learned about the event. Installation ("internal")
repos learn about it from a **webhook** (`app.api.routes.webhooks`); external
repos, which receive no webhooks, learn about it by **polling** the REST API
(`app.workers.tasks.polling`).

Each function here takes an already-resolved ORM object (a ``Repository`` or a
``PullRequest``) plus normalized primitives — never a raw GitHub payload. The
two entry points differ only in how they turn their source (a webhook body vs a
REST snapshot) into those inputs; from here on the handling is common.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlmodel import Session, col, select

from app.models import (
    CIStatus,
    FindingResolutionReason,
    FixStatus,
    PullRequest,
    Repository,
    ReviewDecision,
    ScanTrigger,
    WorkflowFinding,
    WorkflowFix,
    WorkflowScan,
)
from app.services import state_machines as sm
from app.services.events import publisher as events_pub
from app.services.events import schemas as ev

logger = logging.getLogger(__name__)


# ─── Normalizers (shared payload → domain mapping) ───────────────────────────


def ci_status_from_conclusion(status: str, conclusion: str | None) -> CIStatus:
    """Map a GitHub check-suite ``status``/``conclusion`` pair to ``CIStatus``.

    Shared so a webhook (``check_suite`` payload) and a poll (a REST check-suite
    snapshot) classify CI identically.
    """
    if status != "completed":
        return CIStatus.pending
    if conclusion == "success":
        return CIStatus.success
    if conclusion in ("failure", "timed_out", "cancelled", "action_required"):
        return CIStatus.failure
    return CIStatus.none


def review_state_to_decision(state: str) -> ReviewDecision | None:
    """Map a GitHub review ``state`` to ``ReviewDecision`` (``None`` = leave as-is).

    A plain comment review carries no decision, so it maps to ``None`` and the
    caller keeps the PR's current value.
    """
    return {
        "approved": ReviewDecision.approved,
        "changes_requested": ReviewDecision.changes_requested,
        "dismissed": ReviewDecision.review_required,
    }.get(state.lower())


# ─── Scan ────────────────────────────────────────────────────────────────────


def enqueue_workflow_analysis(
    repo: Repository,
    branch: str,
    commit_sha: str,
    trigger: ScanTrigger,
    force: bool = False,
) -> None:
    """Enqueue a static analysis for ``branch`` and announce it over SSE.

    Skips ``greensecops/`` branches (the app's own fix branches) so an analysis
    never self-triggers on a fix PR. Shared by the ``push``/``workflow_run``
    webhooks, the ``polled_push`` poller and the ``reanalyze`` command.
    """
    if branch.startswith("greensecops/"):
        return
    from app.workers.tasks.static_analysis import run_static_analysis

    run_static_analysis.delay(
        repo_id=str(repo.id),
        branch=branch,
        commit_sha=commit_sha,
        trigger=trigger.value,
        force=force,
    )
    events_pub.publish_event(
        ev.analysis_queued(str(repo.org_id), str(repo.id), branch, trigger.value)
    )


def enqueue_terraform_scans(
    session: Session,
    repo: Repository,
    branch: str,
    commit_sha: str,
    trigger: ScanTrigger,
    changed_paths: set[str] | None,
) -> None:
    """Enqueue a scan for every enabled TerraformRoot a push touched.

    ``changed_paths`` is the set of file paths the push added/modified/
    removed; ``None`` means "unknown" (a new branch, or a force-push whose
    payload can't be trusted to list every changed file — the workflow-
    analysis push handler applies the same unconditional-rescan rule for
    the same reason) and scans every enabled root regardless of path.

    Only fires on the default branch: unlike workflow analysis (which tracks
    every branch so PR-branch issues stay visible), TerraformRoot has no
    per-branch tracking yet — last_scanned_head_sha assumes one branch.
    """
    if branch != repo.default_branch or branch.startswith("greensecops/"):
        return
    from app.models import TerraformRoot

    roots = session.exec(
        select(TerraformRoot)
        .where(TerraformRoot.repo_id == repo.id)
        .where(TerraformRoot.enabled == True)  # noqa: E712
    ).all()
    for root in roots:
        if changed_paths is not None and not any(
            p == root.root_path or p.startswith(f"{root.root_path}/")
            for p in changed_paths
        ):
            continue
        from app.workers.tasks.terraform_analysis import run_terraform_scan

        run_terraform_scan.delay(
            terraform_root_id=str(root.id),
            branch=branch,
            commit_sha=commit_sha,
            trigger=trigger.value,
        )


def enqueue_ansible_scans(
    session: Session,
    repo: Repository,
    branch: str,
    commit_sha: str,
    trigger: ScanTrigger,
    changed_paths: set[str] | None,
) -> None:
    """Enqueue a scan for every enabled AnsibleProject a push touched.

    Same contract as ``enqueue_terraform_scans``: default branch only, and a
    ``None`` ``changed_paths`` (new branch, or a force-push whose payload cannot
    be trusted) rescans every enabled project regardless of path.

    The path filter tolerates a project rooted at ``""`` — the repository root,
    which prefixes everything — the way the Docker handler does, because an
    Ansible project registered at the root should match any push.
    """
    if branch != repo.default_branch or branch.startswith("greensecops/"):
        return
    from app.models import AnsibleProject

    projects = session.exec(
        select(AnsibleProject)
        .where(AnsibleProject.repo_id == repo.id)
        .where(AnsibleProject.enabled == True)  # noqa: E712
    ).all()
    for project in projects:
        if (
            changed_paths is not None
            and project.root_path
            and not any(
                p == project.root_path or p.startswith(f"{project.root_path}/")
                for p in changed_paths
            )
        ):
            continue
        from app.workers.tasks.ansible_analysis import run_ansible_scan

        run_ansible_scan.delay(
            ansible_project_id=str(project.id),
            branch=branch,
            commit_sha=commit_sha,
            trigger=trigger.value,
        )


def enqueue_docker_scans(
    session: Session,
    repo: Repository,
    branch: str,
    commit_sha: str,
    trigger: ScanTrigger,
    changed_paths: set[str] | None,
) -> None:
    """Enqueue a scan for every enabled DockerTarget a push touched.

    Same contract as ``enqueue_terraform_scans``: ``changed_paths`` of
    ``None`` means "unknown" (new branch or force-push) and scans every
    enabled target; default branch only, since DockerTarget has no per-branch
    tracking.

    The path filter differs in one respect. A Terraform root is always a real
    directory, but a Docker target's ``root_path`` is ``""`` for the common
    repository-root case, and every path is "under" the empty string — so an
    empty root matches any push, which is exactly right for a target that
    covers the whole repository.
    """
    if branch != repo.default_branch or branch.startswith("greensecops/"):
        return
    from app.models import DockerTarget

    targets = session.exec(
        select(DockerTarget)
        .where(DockerTarget.repo_id == repo.id)
        .where(DockerTarget.enabled == True)  # noqa: E712
    ).all()
    for target in targets:
        if (
            changed_paths is not None
            and target.root_path
            and not any(
                p == target.root_path or p.startswith(f"{target.root_path}/")
                for p in changed_paths
            )
        ):
            continue
        from app.workers.tasks.docker_analysis import run_docker_scan

        run_docker_scan.delay(
            docker_target_id=str(target.id),
            branch=branch,
            commit_sha=commit_sha,
            trigger=trigger.value,
        )


# ─── Pull-request lifecycle ──────────────────────────────────────────────────


def handle_pull_request_lifecycle(
    session: Session,
    pr_record: PullRequest,
    event: str,
) -> None:
    """Apply a PR open/closed/merged transition and its fix/issue side effects.

    ``event`` is one of ``"merge"``, ``"close"`` or ``"reopen"``.

    - ``merge``: land delivered fixes (terminal) and resolve their issues with
      reason ``merged``.
    - ``close`` (not merged): supersede delivered fixes so a later ``reopen``
      can restore them.
    - ``reopen``: restore fixes the closed-PR guard auto-superseded.

    ``sm.try_advance`` keeps this idempotent: GitHub may redeliver or reorder
    events, and a poll may observe a transition a webhook already applied.
    """
    merged = event == "merge"

    sm.try_advance(pr_record, sm.PullRequestMachine, event)
    session.add(pr_record)
    session.commit()
    logger.info(
        "PR %s -> state=%s for PR record %s",
        pr_record.pr_url,
        pr_record.pr_state,
        pr_record.id,
    )

    pr_fixes = list(
        session.exec(select(WorkflowFix).where(WorkflowFix.pr_id == pr_record.id)).all()
    )

    if event == "reopen":
        # Reopening withdraws the close-as-rejection signal: fixes the closed-PR
        # delivery guard auto-rejected (``superseded_by_closed_pr``) become
        # deliverable again. User-rejected fixes keep their status.
        for pr_fix in pr_fixes:
            if pr_fix.status == FixStatus.superseded_by_closed_pr:
                sm.advance(pr_fix, sm.FixMachine, "restore")
                session.add(pr_fix)
        session.commit()
    elif event == "close":
        # A delivered PR closed without merging withdraws its fixes: move them to
        # ``superseded_by_closed_pr`` so ``reopen`` restores them. try_advance
        # keeps it a no-op for any already-terminal fix.
        superseded_fixes: list[WorkflowFix] = []
        for pr_fix in pr_fixes:
            if sm.try_advance(pr_fix, sm.FixMachine, "supersede_closed_pr"):
                session.add(pr_fix)
                superseded_fixes.append(pr_fix)
        if superseded_fixes:
            session.commit()
            repo = session.get(Repository, pr_record.repo_id)
            if repo:
                for pr_fix in superseded_fixes:
                    events_pub.publish_event(
                        ev.fix_rejected(str(repo.org_id), str(repo.id), str(pr_fix.id))
                    )
    elif event == "merge":
        # The PR merged: land its delivered fixes (terminal) and resolve the
        # issues they addressed — the code is now on the branch. try_advance
        # keeps non-``delivered`` fixes untouched.
        landed_fixes: list[WorkflowFix] = []
        for pr_fix in pr_fixes:
            if sm.try_advance(pr_fix, sm.FixMachine, "land"):
                session.add(pr_fix)
                landed_fixes.append(pr_fix)
        if landed_fixes:
            _resolve_issues_for_landed_fixes(session, landed_fixes)
            session.commit()
            repo = session.get(Repository, pr_record.repo_id)
            if repo:
                for pr_fix in landed_fixes:
                    events_pub.publish_event(
                        ev.fix_landed(str(repo.org_id), str(repo.id), str(pr_fix.id))
                    )

    fix = pr_fixes[0] if pr_fixes else None
    if fix:
        repo = session.get(Repository, pr_record.repo_id)
        if repo:
            if event in ("close", "merge"):
                events_pub.publish_event(
                    ev.pr_closed(
                        str(repo.org_id),
                        str(repo.id),
                        str(fix.id),
                        pr_record.pr_url or "",
                        merged,
                    )
                )
            else:
                events_pub.publish_event(
                    ev.pr_opened(
                        str(repo.org_id),
                        str(repo.id),
                        [str(fix.id)],
                        pr_record.pr_url or "",
                        pr_record.pr_branch,
                    )
                )


def _resolve_issues_for_landed_fixes(
    session: Session,
    fixes: list[WorkflowFix],
) -> None:
    """Resolve the still-open issues addressed by merged (landed) fixes.

    Sets ``resolved_at`` + ``resolution_reason = merged``. Idempotent: a later
    re-analysis leaves already-resolved issues alone, and a recurring violation
    reopens via the usual on-conflict path.
    """
    now = datetime.now(timezone.utc)
    fix_ids = [f.id for f in fixes]
    issues = session.exec(
        select(WorkflowFinding)
        .where(col(WorkflowFinding.fix_id).in_(fix_ids))
        .where(col(WorkflowFinding.resolved_at).is_(None))
    ).all()
    for issue in issues:
        issue.resolved_at = now
        issue.resolution_reason = FindingResolutionReason.merged
        session.add(issue)


def _publish_pr_updated(session: Session, pr_record: PullRequest) -> None:
    """Publish a ``pr.updated`` SSE event carrying all fixes on the PR."""
    repo = session.get(Repository, pr_record.repo_id)
    if not repo:
        return
    pr_fixes = list(
        session.exec(select(WorkflowFix).where(WorkflowFix.pr_id == pr_record.id)).all()
    )
    events_pub.publish_event(
        ev.pr_updated(
            str(repo.org_id),
            str(repo.id),
            [str(f.id) for f in pr_fixes],
            pr_record.pr_url or "",
            pr_record.pr_branch,
        )
    )


def handle_pull_request_draft_toggle(
    session: Session,
    pr_record: PullRequest,
    event: str,
) -> None:
    """Record a converted_to_draft / ready_for_review toggle (state + SSE).

    ``event`` is ``"convert_to_draft"`` or ``"mark_ready_for_review"``.
    """
    if not sm.try_advance(pr_record, sm.PullRequestMachine, event):
        # Not in a state the toggle applies to (e.g. already merged/closed).
        return
    pr_record.updated_at = datetime.now(timezone.utc)
    session.add(pr_record)
    session.commit()

    _publish_pr_updated(session, pr_record)
    logger.info(
        "PR %s draft toggle %s recorded (record %s)",
        pr_record.pr_url,
        event,
        pr_record.id,
    )


def handle_pull_request_sync(
    session: Session,
    pr_record: PullRequest,
    mergeable_state: str | None = None,
) -> None:
    """Record a synchronize/edited event on an open PR (updated_at + SSE)."""
    if not sm.try_advance(pr_record, sm.PullRequestMachine, "external_update"):
        # PR is not open/draft (closed/merged/NULL): nothing to record.
        return
    pr_record.updated_at = datetime.now(timezone.utc)
    if mergeable_state is not None:
        pr_record.mergeable_state = mergeable_state[:32]
    session.add(pr_record)
    session.commit()

    _publish_pr_updated(session, pr_record)
    logger.info(
        "PR %s external update recorded (record %s)", pr_record.pr_url, pr_record.id
    )


def handle_ci_status(
    session: Session,
    pr_record: PullRequest,
    ci_status: CIStatus,
) -> None:
    """Record a PR's CI outcome (an attribute, not a state) and announce it."""
    pr_record.ci_status = ci_status
    session.add(pr_record)
    session.commit()
    _publish_pr_updated(session, pr_record)


def handle_review_decision(
    session: Session,
    pr_record: PullRequest,
    decision: ReviewDecision,
) -> None:
    """Record a PR's latest review decision (an attribute) and announce it."""
    pr_record.review_decision = decision
    session.add(pr_record)
    session.commit()
    _publish_pr_updated(session, pr_record)


# ─── Slash commands ──────────────────────────────────────────────────────────


#: Verbs recognised by ``/greensecops`` comment commands. Other commands
#: (fix, ...) are not implemented yet.
GREENSECOPS_COMMAND_VERBS = ("reanalyze", "ignore", "unignore")


def parse_greensecops_command(body: str) -> list[str] | None:
    """Parse a ``/greensecops <verb> ...`` comment; ``None`` if not a command."""
    stripped = body.strip()
    if not stripped.startswith("/greensecops"):
        return None
    command = stripped.removeprefix("/greensecops").strip().split()
    if not command or command[0] not in GREENSECOPS_COMMAND_VERBS:
        return None
    return command


def handle_issue_command(
    session: Session,
    repo: Repository,
    command: list[str],
) -> None:
    """Dispatch a parsed ``/greensecops`` command (``command[0]`` is the verb).

    The caller has already stripped the ``/greensecops`` prefix and split the
    arguments (see ``parse_greensecops_command``).
    """
    if not command or command[0] not in GREENSECOPS_COMMAND_VERBS:
        return

    if command[0] == "reanalyze":
        enqueue_workflow_analysis(
            repo,
            branch=repo.default_branch,
            commit_sha="",
            trigger=ScanTrigger.manual,
            force=True,
        )
    else:
        # ``/greensecops ignore|unignore <fingerprint>`` mutes/un-mutes every
        # issue in this repo carrying that fingerprint (a stable per-violation
        # id). The status trigger recomputes ``status`` from ``ignored_at``.
        _handle_issue_ignore_command(session, repo, command)


def _handle_issue_ignore_command(
    session: Session,
    repo: Repository,
    command: list[str],
) -> None:
    if len(command) < 2:
        logger.info("`/greensecops %s` requires a fingerprint argument", command[0])
        return
    fingerprint = command[1]
    issues = list(
        session.exec(
            select(WorkflowFinding)
            .join(WorkflowScan, WorkflowFinding.analysis_id == WorkflowScan.id)  # type: ignore[arg-type]
            .where(WorkflowScan.repo_id == repo.id)
            .where(WorkflowFinding.fingerprint == fingerprint)
        ).all()
    )
    if not issues:
        return
    now = datetime.now(timezone.utc) if command[0] == "ignore" else None
    for issue in issues:
        issue.ignored_at = now
        session.add(issue)
    session.commit()
    logger.info(
        "%s %d issue(s) with fingerprint %s in repo %s",
        "Ignored" if now else "Un-ignored",
        len(issues),
        fingerprint,
        repo.id,
    )
