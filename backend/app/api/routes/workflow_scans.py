import uuid
from typing import Any

from fastapi import HTTPException, Query
from sqlmodel import col, func, select

from app.api.deps import (
    CurrentUser,
    GitHubOidcClaims,
    SessionDep,
    authorize_repo,
    get_or_404,
    user_org_ids,
)
from app.api.engine_routes import (
    repo_from_oidc_claims,
    repository_activity,
    require_idle,
    sarif_for_claims,
    workflow_file_activity,
)
from app.api.mappers import to_workflow_scan_public
from app.api.router import Role, RoleRouter
from app.core.rate_limit import LIMIT_EXPENSIVE, LIMIT_INGEST
from app.models import (
    Engine,
    Repository,
    ScanStatus,
    TargetAction,
    WorkflowFile,
    WorkflowFilePublic,
    WorkflowScan,
    WorkflowScanPublic,
)
from app.services.billing.quota import enforce_quota
from app.services.events import publisher as events_pub
from app.services.events import schemas as ev
from app.workers.tasks.static_analysis import (
    reanalyze_all_repositories,
    run_static_analysis,
)

router = RoleRouter()


@router.get("/scans", role=Role.user, response_model=list[WorkflowScanPublic])
def list_scans(
    session: SessionDep,
    current_user: CurrentUser,
    repo_id: uuid.UUID | None = None,
    branch: str | None = None,
    grade: str | None = None,
    status: ScanStatus | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=200),
) -> list[WorkflowScanPublic]:
    query = select(WorkflowScan)
    if not current_user.is_superuser:
        query = query.where(
            WorkflowScan.repo_id.in_(  # type: ignore[attr-defined]
                select(Repository.id).where(
                    Repository.org_id.in_(user_org_ids(session, current_user))  # type: ignore[attr-defined]
                )
            )
        )
    if repo_id:
        query = query.where(WorkflowScan.repo_id == repo_id)
    if branch:
        query = query.where(WorkflowScan.branch == branch)
    if grade:
        query = query.where(WorkflowScan.grade == grade)
    if status:
        query = query.where(WorkflowScan.status == status)
    query = (
        query.order_by(col(WorkflowScan.created_at).desc()).offset(skip).limit(limit)
    )
    return [to_workflow_scan_public(a) for a in session.exec(query).all()]


@router.get("/scans/{scan_id}", role=Role.org_member, response_model=WorkflowScanPublic)
def get_scan(
    scan_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> WorkflowScanPublic:
    analysis = get_or_404(session, WorkflowScan, scan_id)
    if not current_user.is_superuser:
        authorize_repo(
            session, current_user, analysis.repo_id, detail="Workflow scan not found"
        )
    return to_workflow_scan_public(analysis)


@router.post(
    "/repositories/{repo_id}/scans",
    role=Role.org_admin,
    limit=LIMIT_EXPENSIVE,
    status_code=202,
)
def trigger_repository_scan(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    branch: str | None = None,
    force: bool = True,
) -> dict[str, str]:
    repo = authorize_repo(session, current_user, repo_id)
    if not repo.is_accessible:
        raise HTTPException(status_code=403, detail="Repository is not accessible")
    require_idle(repository_activity(session, repo_id), TargetAction.scan, "repository")

    effective_branch = branch or repo.default_branch
    # One trigger fans out to one analysis *per workflow file*, so checking for
    # a single unit here let a user one below their cap create twenty. The
    # exact count is only known once the worker re-fetches from GitHub; the
    # files we already know about on this branch are the best estimate
    # available, and the worker's own gate stops the batch at the true cap
    # either way.
    known_files = session.exec(
        select(func.count(col(WorkflowFile.id)))
        .where(WorkflowFile.repo_id == repo_id)
        .where(WorkflowFile.branch == effective_branch)
        .where(col(WorkflowFile.deleted_at).is_(None))
    ).one()
    enforce_quota(
        session,
        current_user,
        repo.org_id,
        "analyses",
        requested=max(int(known_files or 0), 1),
    )
    run_static_analysis.delay(
        repo_id=str(repo_id),
        branch=effective_branch,
        trigger="manual",
        force=force,
    )
    events_pub.publish_event(
        ev.analysis_queued(str(repo.org_id), str(repo_id), effective_branch, "manual")
    )
    return {"status": "queued", "repo_id": str(repo_id)}


@router.post(
    "/files/{workflow_file_id}/scans",
    role=Role.org_admin,
    limit=LIMIT_EXPENSIVE,
    status_code=202,
)
def trigger_file_scan(
    workflow_file_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    force: bool = True,
) -> dict[str, str]:
    """Re-run static analysis for a single workflow file.

    Per-file analog of ``trigger_repository_scan`` (which is repo/branch-wide):
    the worker re-fetches and re-evaluates just this file on its own branch,
    consistent with the per-file fix and delivery endpoints alongside it.
    """
    wf_file = get_or_404(session, WorkflowFile, workflow_file_id)
    repo = authorize_repo(session, current_user, wf_file.repo_id)
    if not repo.is_accessible:
        raise HTTPException(status_code=403, detail="Repository is not accessible")
    require_idle(
        workflow_file_activity(session, wf_file), TargetAction.scan, "workflow file"
    )

    enforce_quota(session, current_user, repo.org_id, "analyses")
    effective_branch = wf_file.branch or repo.default_branch
    run_static_analysis.delay(
        repo_id=str(repo.id),
        branch=effective_branch,
        trigger="manual",
        workflow_file_id=str(workflow_file_id),
        force=force,
    )
    events_pub.publish_event(
        ev.analysis_queued(str(repo.org_id), str(repo.id), effective_branch, "manual")
    )
    return {"status": "queued", "workflow_file_id": str(workflow_file_id)}


@router.post(
    "/scans/backfill",
    role=Role.admin,
    limit=LIMIT_EXPENSIVE,
    status_code=202,
)
def backfill_scans() -> dict[str, str]:
    """Fan out a fresh static analysis across all enabled repositories.

    Same mechanism used automatically when a release ships new rules; exposed
    so operators can re-apply rules on demand without a redeploy.
    """
    reanalyze_all_repositories.delay()
    return {"status": "queued"}


@router.get(
    "/repositories/{repo_id}/files",
    role=Role.org_member,
    response_model=list[WorkflowFilePublic],
)
def list_files(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    branch: str | None = None,
) -> list[WorkflowFilePublic]:
    repo = authorize_repo(session, current_user, repo_id)
    wf_files = session.exec(
        select(WorkflowFile)
        .where(WorkflowFile.repo_id == repo.id)
        .where(WorkflowFile.branch == (branch or repo.default_branch))
        # Soft-deleted files (path removed from the repo) are kept for history
        # but must not show as current workflows.
        .where(col(WorkflowFile.deleted_at).is_(None))
    ).all()
    return [
        WorkflowFilePublic(
            id=wf.id,
            path=wf.path,
            branch=wf.branch,
            raw_content=wf.raw_content,
            source_commit_sha=wf.source_commit_sha,
            fetched_at=wf.fetched_at,
        )
        for wf in wf_files
    ]


@router.get("/sarif", role=Role.service, limit=LIMIT_INGEST)
def get_sarif(
    session: SessionDep,
    claims: GitHubOidcClaims,
) -> dict[str, Any]:
    """This repository's open CI-workflow findings as a SARIF 2.1.0 log.

    For a workflow that runs ``upload-sarif`` on its own runner, so a team can
    read GreenSecOps findings in the security tab and on the PR diff alongside
    whatever else they scan with — the same findings, in the format GitHub
    reads, without installing the App.

    Authenticated by the run's GitHub OIDC token: the repository comes from the
    signed claim, so no id is needed and none would be honoured.
    """
    return sarif_for_claims(Engine.workflow, session, claims)


@router.post("/scans", role=Role.service, limit=LIMIT_EXPENSIVE, status_code=202)
def trigger_scans_for_code_scanning(
    session: SessionDep,
    claims: GitHubOidcClaims,
    branch: str | None = None,
) -> dict[str, str]:
    """Re-scan the calling repository's workflow files.

    The first half of the Code Scanning flow: a workflow asks for fresh
    analysis and then fetches ``GET /workflow/sarif``. Without it a team using
    the workflows rather than the App would only ever publish whatever the last
    scan found — nothing at all, on a repository the App has never touched.

    Repo-level rather than a fan-out over targets, unlike the other three
    engines: the CI engine's own worker discovers the workflow files from
    GitHub, so handing it a list built from our rows would scan a stale set.

    Authenticated by the run's GitHub OIDC token, so the repository is the one
    the token was minted for. Quota is charged to the org's billing owner,
    exactly as a dashboard-triggered scan is; there is no user to attribute it
    to, and the worker re-checks the allowance before doing the work.
    """
    repo = repo_from_oidc_claims(session, claims)
    effective_branch = branch or repo.default_branch
    known_files = session.exec(
        select(func.count(col(WorkflowFile.id)))
        .where(WorkflowFile.repo_id == repo.id)
        .where(WorkflowFile.branch == effective_branch)
        .where(col(WorkflowFile.deleted_at).is_(None))
    ).one()
    enforce_quota(
        session,
        None,
        repo.org_id,
        "analyses",
        requested=max(int(known_files or 0), 1),
    )
    run_static_analysis.delay(
        repo_id=str(repo.id),
        branch=effective_branch,
        trigger="code_scanning",
        force=True,
    )
    return {"status": "queued", "repo_id": str(repo.id)}
