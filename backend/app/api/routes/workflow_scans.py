import uuid

from fastapi import HTTPException, Query
from sqlmodel import col, func, select

from app.api.deps import (
    CurrentUser,
    SessionDep,
    authorize_repo,
    get_or_404,
    user_org_ids,
)
from app.api.mappers import to_analysis_public
from app.api.router import Role, RoleRouter
from app.core.rate_limit import LIMIT_EXPENSIVE
from app.models import (
    AnalysisPublic,
    Repository,
    ScanStatus,
    WorkflowFile,
    WorkflowScan,
)
from app.services.billing.quota import enforce_quota
from app.services.events import publisher as events_pub
from app.services.events import schemas as ev
from app.workers.tasks.static_analysis import (
    reanalyze_all_repositories,
    run_static_analysis,
)

router = RoleRouter()


@router.get("/", role=Role.user, response_model=list[AnalysisPublic])
def list_analyses(
    session: SessionDep,
    current_user: CurrentUser,
    repo_id: uuid.UUID | None = None,
    branch: str | None = None,
    grade: str | None = None,
    status: ScanStatus | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=200),
) -> list[AnalysisPublic]:
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
    return [to_analysis_public(a) for a in session.exec(query).all()]


@router.get("/{analysis_id}", role=Role.org_member, response_model=AnalysisPublic)
def get_analysis(
    analysis_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> AnalysisPublic:
    analysis = get_or_404(session, WorkflowScan, analysis_id)
    if not current_user.is_superuser:
        authorize_repo(
            session, current_user, analysis.repo_id, detail="Workflow scan not found"
        )
    return to_analysis_public(analysis)


@router.post(
    "/trigger/{repo_id}", role=Role.org_admin, limit=LIMIT_EXPENSIVE, status_code=202
)
def trigger_analysis(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    branch: str | None = None,
    force: bool = True,
) -> dict[str, str]:
    repo = authorize_repo(session, current_user, repo_id)
    if not repo.is_accessible:
        raise HTTPException(status_code=403, detail="Repository is not accessible")

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
    "/reanalyze-for-workflow/{workflow_file_id}",
    role=Role.org_admin,
    limit=LIMIT_EXPENSIVE,
    status_code=202,
)
def reanalyze_for_workflow(
    workflow_file_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    force: bool = True,
) -> dict[str, str]:
    """Re-run static analysis for a single workflow file.

    Per-workflow analog of ``trigger_analysis`` (which is repo/branch-wide):
    the worker re-fetches and re-evaluates just this file on its own branch,
    consistent with the per-workflow fix (``regenerate-for-workflow``) and
    delivery (``deliver-for-workflow``) endpoints.
    """
    wf_file = get_or_404(session, WorkflowFile, workflow_file_id)
    repo = authorize_repo(session, current_user, wf_file.repo_id)
    if not repo.is_accessible:
        raise HTTPException(status_code=403, detail="Repository is not accessible")

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
    "/reanalyze-all",
    role=Role.admin,
    limit=LIMIT_EXPENSIVE,
    status_code=202,
)
def reanalyze_all() -> dict[str, str]:
    """Fan out a fresh static analysis across all enabled repositories.

    Same mechanism used automatically when a release ships new rules; exposed
    so operators can re-apply rules on demand without a redeploy.
    """
    reanalyze_all_repositories.delay()
    return {"status": "queued"}
